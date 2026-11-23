"""Deep history for every stock in the lineup: every SEC filing since each company's first on EDGAR (Cameco and Denison
from 1998, Centrus as USEC from 1998, Uranium Energy from 2005, Energy Fuels from 2006, BWXT as Babcock & Wilcox from
2010...) and company news from 2008 to 2018 (before the main archive starts). Stored apart from the bot's live memory so
the always-on computer and this backfill never write the same file.

memory/history_events.json   events with outcomes (filled from prices since 2006)
memory/history/headlines/     the old headlines by company
"""
import datetime as dt, json, os, time, urllib.parse, urllib.request

import feedparser

import archive, collector, desk_memory

ROOT = os.path.dirname(os.path.abspath(__file__))
EVENTS = os.path.join(ROOT, "memory", "history_events.json")
HDIR = os.path.join(ROOT, "memory", "history", "headlines")
UA = desk_memory.UA


def _get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30))


def sec_full(tickers):
    """Every 8-K/6-K/424B5 each company ever filed on EDGAR (the 'recent' list plus the older filing files)."""
    m = {v["ticker"]: str(v["cik_str"]).zfill(10) for v in _get("https://www.sec.gov/files/company_tickers.json").values()}
    ev = archive._load(EVENTS, [])
    seen = {(e["ticker"], e["date"], e["title"]) for e in ev}
    n = 0
    for t in tickers:
        cik = m.get(t)
        if not cik:
            continue
        d = _get(f"https://data.sec.gov/submissions/CIK{cik}.json")
        blocks = [d["filings"]["recent"]] + [_get(f"https://data.sec.gov/submissions/{f['name']}") for f in d["filings"].get("files", [])]
        for f in blocks:
            for form, date, items, desc in zip(f["form"], f["filingDate"], f.get("items", [""] * len(f["form"])),
                                               f.get("primaryDocDescription", [""] * len(f["form"]))):
                if form not in ("8-K", "6-K", "424B5") or date >= "2019-01-01":  # 2019+ is already in the live memory
                    continue
                if form == "424B5":
                    typ, title = "offering_dilution", "424B5 filed: share offering (prospectus supplement)"
                else:
                    its = [i.strip() for i in (items or "").split(",") if i.strip() in desk_memory.ITEMS]
                    if form == "8-K" and not its:
                        continue
                    typ = desk_memory.ITEMS[its[0]] if its else "company_update"
                    title = f"{form} filed: {', '.join(desk_memory.ITEMS.get(i, i) for i in its) or (desc or 'report')}"
                if (t, date, title) in seen:
                    continue
                seen.add((t, date, title))
                ev.append({"ticker": t, "date": date, "title": title, "type": typ, "source": "SEC (full history)",
                           "r0": None, "r1": None, "r5": None, "r20": None, "r60": None, "x5": None, "x20": None})
                n += 1
        time.sleep(0.3)
    archive._save(EVENTS, ev)
    return n


def news_old(budget_s=3000, start=dt.date(2008, 1, 7), end=dt.date(2019, 1, 7), part=None, pause=1.0):
    """Company and sector news 2008-2018 in month windows (resumable). part='i/n' splits topics across parallel runs."""
    cur_p = os.path.join(os.path.dirname(HDIR), "cursor.json")
    cur = archive._load(cur_p, {})
    tps = archive.topics()
    if part:
        i, n = map(int, part.split("/"))
        tps = {k: v for j, (k, v) in enumerate(sorted(tps.items())) if j % n == i}
    ev = archive._load(EVENTS, [])
    seen = {(e["ticker"], e["date"], e["title"]) for e in ev}
    t0, reads, added = time.time(), 0, 0
    while time.time() - t0 < budget_s:
        todo = [k for k in tps if dt.date.fromisoformat(cur.get(k, str(start))) < end]
        if not todo:
            break
        for k in todo:
            if time.time() - t0 >= budget_s:
                break
            a = dt.date.fromisoformat(cur.get(k, str(start))); b = min(a + dt.timedelta(days=28), end)
            q, tk = tps[k]
            url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": f"{q} after:{a} before:{b}", "hl": "en-US", "gl": "US", "ceid": "US:en"})
            try:
                ents = feedparser.parse(url, agent="Mozilla/5.0 SwingDesk research").entries
            except Exception:
                time.sleep(5); continue
            path = os.path.join(HDIR, k.replace(":", "_").replace(" ", "_").replace("(", "").replace(")", "") + ".json")
            hl = archive._load(path, [])
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
                for tag in [x for x in collector._tags(title) if x in collector.MEMORY_TAGS + ("price", "restart", "jobs")][:2]:
                    key = (tk, d, title[:160])
                    if key in seen:
                        continue
                    seen.add(key)
                    ev.append({"ticker": tk, "date": d, "title": title[:160], "type": f"news_{tag}", "source": f"history:{k}",
                               "r0": None, "r1": None, "r5": None, "r20": None, "r60": None, "x5": None, "x20": None})
                    added += 1
            os.makedirs(HDIR, exist_ok=True)
            archive._save(path, hl)
            cur[k] = str(b); reads += 1
            if reads % 20 == 0:
                archive._save(EVENTS, ev); archive._save(cur_p, cur)
            time.sleep(pause)
    archive._save(EVENTS, ev); archive._save(cur_p, cur)
    return {"reads": reads, "added": added, "total": len(ev)}


if __name__ == "__main__":
    import sys
    if sys.argv[1] == "sec":
        print(sec_full(["CCJ", "NXE", "UEC", "DNN", "UUUU", "LEU", "BWXT", "CEG", "VST", "TLN"]), "filings added")
    else:
        print(news_old(int(sys.argv[2]) if len(sys.argv) > 2 else 3000, part=os.environ.get("PART")))
