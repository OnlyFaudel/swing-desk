"""Earnings reader: after each company reports, read the actual results release filed with the SEC (8-K item 2.02 for US
companies, the 6-K results exhibit for Canadian ones), pull out the numbers, the guidance and every concrete PROMISE
management made with a date, and put those promises on the calendar so the bot later checks whether they delivered.
"""
import json, re, datetime as dt, urllib.request
import desk_memory

UA = desk_memory.UA


def _get(url, raw=False):
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30).read()
    return r.decode("utf-8", "ignore") if raw else json.loads(r)


_CIK = {}


def cik(t):
    if not _CIK:
        _CIK.update({v["ticker"]: str(v["cik_str"]).zfill(10) for v in _get("https://www.sec.gov/files/company_tickers.json").values()})
    return _CIK.get(t)


def _text(c, acc, primary):
    base = f"https://www.sec.gov/Archives/edgar/data/{int(c)}/{acc.replace('-', '')}"
    items = _get(base + "/index.json")["directory"]["item"]
    htm = [f for f in items if f["name"].lower().endswith((".htm", ".html")) and f["name"] != primary and "index" not in f["name"]]
    ex = [f["name"] for f in htm if re.search(r"ex[-_]?99|exhibit99|ex991|99[-_]?1", f["name"], re.I)]
    big = sorted(htm, key=lambda f: -int(f.get("size") or 0))
    html = _get(f"{base}/{(ex or [b['name'] for b in big] or [primary])[0]}", raw=True)
    txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"&nbsp;|&#160;", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def results_filings(t, since_days=5):
    """Results releases filed in the last since_days days: [{form, date, accession, text}]."""
    c = cik(t)
    if not c:
        return []
    r = _get(f"https://data.sec.gov/submissions/CIK{c}.json")["filings"]["recent"]
    cut = str(dt.date.today() - dt.timedelta(days=since_days))
    out = []
    for i in range(len(r["form"])):
        f, d = r["form"][i], r["filingDate"][i]
        if d < cut:
            break
        if f == "8-K" and "2.02" in (r["items"][i] or ""):
            pass
        elif f != "6-K":
            continue
        try:
            txt = _text(c, r["accessionNumber"][i], r["primaryDocument"][i])
        except Exception:
            continue
        head = txt[:4000].lower()
        if f == "6-K" and not (("quarter" in head or "annual" in head) and any(w in head for w in ("results", "financial", "earnings"))):
            continue
        out.append({"form": f, "date": d, "accession": r["accessionNumber"][i], "text": txt[:22000]})
    return out
