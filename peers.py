"""Related companies' events (read-through): SEC filings from nuclear peers outside our lineup (Oklo, NuScale, Nano
Nuclear, Lightbridge, GE Vernova). Their earnings, deals and share sales can move the whole group, as Oklo's earnings
did on Nov 9, 2026 (CCJ +5.7% that day). Stored as events on the basket ("_basket") so the discovery engine tests
what each kind of peer event did to our 10 stocks.
"""
import json, os, urllib.request

import archive, desk_memory

PEERS = {"OKLO": "Oklo", "SMR": "NuScale", "NNE": "Nano Nuclear", "LTBR": "Lightbridge", "GEV": "GE Vernova"}


def run(since="2019-01-01"):
    ev = archive._load(archive.EVENTS, [])
    seen = {(e["ticker"], e["date"], e["title"]) for e in ev}
    req = urllib.request.Request("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": desk_memory.UA})
    m = {v["ticker"]: str(v["cik_str"]).zfill(10) for v in json.load(urllib.request.urlopen(req, timeout=20)).values()}
    n = 0
    for t, name in PEERS.items():
        cik = m.get(t)
        if not cik:
            continue
        r = urllib.request.Request(f"https://data.sec.gov/submissions/CIK{cik}.json", headers={"User-Agent": desk_memory.UA})
        f = json.load(urllib.request.urlopen(r, timeout=20))["filings"]["recent"]
        for form, date, items in zip(f["form"], f["filingDate"], f.get("items", [""] * len(f["form"]))):
            if date < since or form not in ("8-K", "424B5"):
                continue
            if form == "424B5":
                typ, what = "offering_dilution", "share offering"
            else:
                its = [i.strip() for i in (items or "").split(",") if i.strip() in desk_memory.ITEMS]
                if not its:
                    continue
                typ = desk_memory.ITEMS[its[0]]; what = ", ".join(desk_memory.ITEMS[i] for i in its)
            key = ("_basket", date, f"{name}: {what}"[:160])
            if key in seen:
                continue
            seen.add(key)
            ev.append({"ticker": "_basket", "date": date, "title": key[2], "type": f"peer_{typ}", "source": f"SEC {t}",
                       "r0": None, "r1": None, "r5": None, "r20": None, "r60": None, "x5": None, "x20": None})
            n += 1
    archive._save(archive.EVENTS, ev)
    return n


if __name__ == "__main__":
    print(run(), "peer events added")
