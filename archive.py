"""News archive builder: years of dated headlines about our companies, the uranium market and government, collected a
little at a time on the always-on computer (nights and weekends), tagged by plain rules, and stored as events whose
outcomes (what the stock or the basket did next) the discovery engine tests. Free, no AI.

Files: memory/archive/headlines/<topic>.json  every headline found, by week
       memory/archive/cursor.json             how far back each topic has been read
       memory/archive_events.json             tagged events (ticker or "_basket" for sector/government news)
"""
import datetime as dt, json, os, time, urllib.parse

import feedparser

import collector

ROOT = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(ROOT, "memory", "archive")
EVENTS = os.path.join(ROOT, "memory", "archive_events.json")
START = dt.date(2019, 1, 7)  # first Monday of 2019

COMPANIES = {"CCJ": '"Cameco"', "NXE": '"NexGen Energy"', "UEC": '"Uranium Energy Corp"', "DNN": '"Denison Mines"',
             "UUUU": '"Energy Fuels"', "LEU": '"Centrus Energy" OR "Centrus"', "BWXT": '"BWX Technologies" OR BWXT',
             "CEG": '"Constellation Energy"', "VST": '"Vistra"', "TLN": '"Talen Energy"'}
SECTOR = {  # these land on the whole basket ("_basket")
    "uranium market": 'uranium (price OR spot OR supply OR mine)',
    "government and laws": '(uranium OR nuclear) (Senate OR Congress OR bill OR "executive order" OR tariff OR ban OR sanctions)',
    "regulator (NRC)": '"Nuclear Regulatory Commission" OR "NRC approves" OR "NRC license"',
    "energy department": '"Department of Energy" (nuclear OR uranium OR HALEU OR reactor)',
    "Kazakhstan and supply": 'Kazatomprom OR "Kazakhstan uranium" OR Niger uranium OR Orano',
    "Sprott and funds": '"Sprott Physical Uranium" OR "uranium ETF" OR "Yellow Cake"',
    "AI power and reactors": 'nuclear ("data center" OR SMR OR "small modular" OR restart)',
    "world new builds": 'nuclear reactor (China OR India OR Korea OR Poland OR Saudi OR Turkey OR Egypt) (approves OR construction OR plan)',
    "defense and geopolitics": '(Iran OR "North Korea" OR Zaporizhzhia OR AUKUS OR NNSA) (uranium OR nuclear)',
}


def _load(p, d):
    try:
        return json.load(open(p))
    except Exception:
        return d


def _save(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(o, open(p, "w"), separators=(",", ":"))


def topics():
    out = {f"co:{t}": (q, t) for t, q in COMPANIES.items()}
    out.update({f"sector:{k}": (q, "_basket") for k, q in SECTOR.items()})
    part = os.environ.get("ARCHIVE_PART")  # "i/n": this process reads every n-th topic (parallel catch-up runs)
    if part:
        i, n = map(int, part.split("/"))
        out = {k: v for j, (k, v) in enumerate(sorted(out.items())) if j % n == i}
    return out


def _weeks_left(cur):
    """Next window to read for a topic: we walk forward from 2019 to last week."""
    last = dt.date.today() - dt.timedelta(days=7)
    d = dt.date.fromisoformat(cur) if cur else START
    return d if d <= last else None


def _span(d):
    """Older history in month-long windows (old news is thin and each search takes seconds), the last 6 months by week."""
    return 7 if d >= dt.date.today() - dt.timedelta(days=183) else 28


def step(budget_s=240, pause=1.3):
    """Read as many week-windows as fit in the time budget, round-robin over topics. Returns a progress summary."""
    cur = _load(os.path.join(DIR, "cursor.json"), {})
    ev = _load(EVENTS, [])
    seen = {(e["ticker"], e["date"], e["title"]) for e in ev}
    T = topics()
    t0, reads, added = time.time(), 0, 0
    while time.time() - t0 < budget_s:
        todo = [k for k in T if _weeks_left(cur.get(k))]
        if not todo:
            break
        for k in todo:
            if time.time() - t0 >= budget_s:
                break
            wk = _weeks_left(cur.get(k))
            q, tk = T[k]
            a, b = wk, wk + dt.timedelta(days=_span(wk))
            url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
                {"q": f"{q} after:{a} before:{b}", "hl": "en-US", "gl": "US", "ceid": "US:en"})
            try:
                ents = feedparser.parse(url, agent="Mozilla/5.0 SwingDesk research").entries
            except Exception:
                ents = None
            if ents is None:
                time.sleep(5)
                continue
            path = os.path.join(DIR, "headlines", k.replace(":", "_").replace(" ", "_").replace("(", "").replace(")", "") + ".json")
            hl = _load(path, [])
            for e in ents[:100]:
                title = collector._clean(e.get("title"), 220)
                title = title.rsplit(" - ", 1)[0] if " - " in title else title
                pub = e.get("published_parsed")
                d = dt.date(*pub[:3]).isoformat() if pub else str(a)
                if not (str(a) <= d <= str(b)):
                    continue
                hl.append({"d": d, "t": title, "src": (e.get("source") or {}).get("title", "")})
                low = title.lower()
                if any(x in low for x in collector.EXCLUDE) or any(c in low for c in collector.CHATTER):
                    continue
                for tag in [t for t in collector._tags(title) if t in collector.MEMORY_TAGS + ("price", "restart", "jobs")][:2]:
                    key = (tk, d, title[:160])
                    if key in seen:
                        continue
                    seen.add(key)
                    ev.append({"ticker": tk, "date": d, "title": title[:160], "type": f"news_{tag}", "source": f"archive:{k}",
                               "r0": None, "r1": None, "r5": None, "r20": None, "r60": None, "x5": None, "x20": None})
                    added += 1
            _save(path, hl)
            cur[k] = str(b)
            reads += 1
            if reads % 20 == 0:  # save progress often, so a stopped run loses almost nothing
                _save(EVENTS, ev)
                _save(os.path.join(DIR, "cursor.json"), cur)
            time.sleep(pause)
    _save(EVENTS, ev)
    _save(os.path.join(DIR, "cursor.json"), cur)
    done = sum(1 for k in T if not _weeks_left(cur.get(k)))
    total = (dt.date.today() - START).days
    pct = sum(min(total, (dt.date.fromisoformat(cur[k]) - START).days) if cur.get(k) else 0 for k in T) / (total * len(T))
    return {"reads": reads, "events_added": added, "events_total": len(ev), "topics_done": done, "topics": len(T), "progress_pct": round(pct * 100, 1)}


def complete():
    cur = _load(os.path.join(DIR, "cursor.json"), {})
    return all(not _weeks_left(cur.get(k)) for k in topics())


if __name__ == "__main__":
    import sys
    print(step(int(sys.argv[1]) if len(sys.argv) > 1 else 60))
