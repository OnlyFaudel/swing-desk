"""Desk Memory: the team's long-term memory, kept in memory/*.json (separate from the day-to-day state).

events.json  every material event (headline, SEC filing, price shock) with what happened after: 1, 5, 20 and 60 trading
             days later, for the stock and versus the 10-stock basket. Backfilled from SEC 8-K filings since 2019, so
             the desk starts with years of history, not zero.
watch.json   dated reminders the team writes for the future ("NRC decision expected Feb 12", "Kazatomprom guidance in
             August"). They come back in the morning meeting when due, so a note from months ago can drive a play.

Retrieval: similar(title) finds past events with overlapping words; playbook(type) averages what that kind of event did.
"""
import datetime as dt, json, os, re, urllib.request
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(ROOT, "memory")
EV, WA = os.path.join(DIR, "events.json"), os.path.join(DIR, "watch.json")
UA = "SwingDesk research swingdesk.bot@gmail.com"
ITEMS = {"1.01": "contract_deal", "1.02": "contract_end", "2.01": "acquisition", "2.02": "earnings", "2.03": "new_debt",
         "3.02": "offering_dilution", "5.02": "leadership_change", "7.01": "company_update", "8.01": "company_update"}
STOP = set("the a an and or of to in on for with at by from as is are was be its it this that after over new says inc corp co".split())


def _load(p, default):
    try:
        return json.load(open(p))
    except Exception:
        return default


def _save(p, obj):
    os.makedirs(DIR, exist_ok=True)
    json.dump(obj, open(p, "w"), indent=0, default=str)


def events():
    return _load(EV, [])


def _words(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2 and w not in STOP}


# ------------------------------------------------------------------ write
def add_event(ticker, title, etype, date=None, source="", materiality=None, direction=None, price=None):
    ev = events()
    d = str(date or dt.date.today())
    if any(e["ticker"] == ticker and e["date"] == d and e["title"] == title[:160] for e in ev[-500:]):
        return
    ev.append({"ticker": ticker, "date": d, "title": title[:160], "type": etype or "other", "source": source,
               "materiality": materiality, "direction_called": direction, "price": price,
               "r0": None, "r1": None, "r5": None, "r20": None, "r60": None, "x5": None, "x20": None})
    del ev[:-20000]
    _save(EV, ev)


def fill(closes, path=None):
    """closes: DataFrame of daily closes (columns = tickers + '_basket'). Fills every outcome that is now known.
    path: another event file (the news archive) instead of the main memory."""
    path = path or EV
    ev, changed = _load(path, []), False
    bk = closes.get("_basket")
    for e in ev:
        if e.get("r60") is not None or e["ticker"] not in closes:
            continue
        c = closes[e["ticker"]].dropna()
        d = pd.Timestamp(e["date"])
        before, after = c[c.index < d], c[c.index >= d]
        if before.empty or after.empty:
            continue
        base = float(before.iloc[-1])  # last close before the event: the day's reaction (r0) is part of the record
        e["r0"] = round((float(after.iloc[0]) / base - 1) * 100, 2)
        for k, n in (("r1", 1), ("r5", 5), ("r20", 20), ("r60", 60)):
            if e.get(k) is None and len(after) > n:
                e[k] = round((float(after.iloc[n]) / float(after.iloc[0]) - 1) * 100, 2)  # AFTER the first day: the tradable part
                changed = True
        if bk is not None and e["ticker"] != "_basket":
            b = bk.dropna(); ba = b[b.index >= d]
            for k, n in (("x5", 5), ("x20", 20)):
                if e.get(k) is None and e.get("r" + k[1:]) is not None and len(ba) > n:
                    e[k] = round(e["r" + k[1:]] - (float(ba.iloc[n]) / float(ba.iloc[0]) - 1) * 100, 2)
        elif e["ticker"] == "_basket":  # sector news: compare with the basket's NORMAL move at that time (its trend over the year before)
            hist = c[c.index < d].iloc[-260:]
            if len(hist) > 60:
                for k, n in (("x1", 1), ("x5", 5), ("x20", 20)):
                    if e.get(k) is None and e.get("r" + k[1:]) is not None:
                        normal = float(((hist.shift(-n) / hist - 1) * 100).dropna().mean())
                        e[k] = round(e["r" + k[1:]] - normal, 2)
    if changed:
        _save(path, ev)


def backfill_sec(tickers, since="2019-01-01"):
    """Years of company events from SEC 8-K filings (contracts, earnings, share sales, leadership changes)."""
    req = urllib.request.Request("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": UA})
    m = {v["ticker"]: str(v["cik_str"]).zfill(10) for v in json.load(urllib.request.urlopen(req, timeout=20)).values()}
    n = 0
    for t in tickers:
        cik = m.get(t)
        if not cik:
            continue
        r = urllib.request.Request(f"https://data.sec.gov/submissions/CIK{cik}.json", headers={"User-Agent": UA})
        f = json.load(urllib.request.urlopen(r, timeout=20))["filings"]["recent"]
        for form, date, items, desc in zip(f["form"], f["filingDate"], f.get("items", [""] * len(f["form"])),
                                           f.get("primaryDocDescription", [""] * len(f["form"]))):
            if date < since or form not in ("8-K", "6-K", "424B5"):
                continue
            if form == "424B5":  # prospectus supplement = the company is selling new shares (dilution)
                add_event(t, "424B5 filed: share offering (prospectus supplement)", "offering_dilution", date, "SEC (backfill)")
                n += 1
                continue
            its = [i.strip() for i in (items or "").split(",") if i.strip() in ITEMS]
            if form == "8-K" and not its:
                continue
            typ = ITEMS[its[0]] if its else "company_update"
            add_event(t, f"{form} filed: {', '.join(ITEMS.get(i, i) for i in its) or (desc or 'report')}", typ, date, "SEC (backfill)")
            n += 1
    return n


# ------------------------------------------------------------------ read
def similar(title, ticker=None, k=5):
    q = _words(title)
    if not q:
        return []
    scored = []
    for e in events():
        if e.get("r5") is None:
            continue
        s = len(q & _words(e["title"])) / max(1, len(q | _words(e["title"])))
        if ticker and e["ticker"] == ticker:
            s += 0.05
        if s > 0.12:
            scored.append((s, e))
    scored.sort(key=lambda x: -x[0])
    return [{k_: e.get(k_) for k_ in ("date", "ticker", "title", "r0", "r5", "r20", "r60", "x20")} for s, e in scored[:k]]


def playbook(etype, tickers=None):
    ev = [e for e in events() if e["type"] == etype and e.get("r20") is not None and (not tickers or e["ticker"] in tickers)]
    if len(ev) < 3:
        return {"n": len(ev)}
    r0, r5, r20 = (np.array([e[k] for e in ev if e.get(k) is not None], float) for k in ("r0", "r5", "r20"))
    x20 = np.array([e["x20"] for e in ev if e.get("x20") is not None], float)
    return {"n": len(ev), "first_day_median_pct": round(float(np.median(r0)), 2) if len(r0) else None,
            "next_5d_median_pct": round(float(np.median(r5)), 2), "next_20d_median_pct": round(float(np.median(r20)), 2),
            "next_20d_vs_basket_median_pct": round(float(np.median(x20)), 2) if len(x20) else None,
            "share_up_20d": round(float((r20 > 0).mean()), 2)}


def all_playbooks(tickers):
    return {t: playbook(t, tickers) for t in sorted({e["type"] for e in events()})}


# ------------------------------------------------------------------ the watch calendar
def watch_add(items, by):
    w = _load(WA, [])
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            d = str(dt.date.fromisoformat(str(it.get("date"))[:10]))
        except ValueError:
            continue
        what = str(it.get("what") or "")[:200]
        if what and not any(x["date"] == d and x["what"] == what for x in w):
            w.append({"date": d, "ticker": str(it.get("ticker") or "")[:6].upper(), "what": what, "by": by,
                      "written": str(dt.date.today()), "surfaced": False})
    w.sort(key=lambda x: x["date"])
    _save(WA, w[-500:])


def watch_due(today, ahead_days=3):
    end = str(today + dt.timedelta(days=ahead_days))
    return [x for x in _load(WA, []) if str(today) <= x["date"] <= end]


def watch_all():
    return _load(WA, [])


def watch_mark(today):
    w = _load(WA, [])
    hit = []
    for x in w:
        if x["date"] <= str(today) and not x["surfaced"]:
            x["surfaced"] = True; hit.append(x)
    if hit:
        _save(WA, w)
    return hit
