"""Reactor watch: every US nuclear reactor's power level, every day, from the NRC's free public file. No AI, no cost.

Why: CEG, VST and TLN earn money when their reactors run. A unit that drops from full power to zero (a trip / scram, or
a refueling outage) is a fact you can see the next morning, often before any headline. The desk records each one with
what the owner's stock did afterwards, so the Research Lab can test "outage -> stock reaction" on real history.

Files (memory/intel/):
  reactors.csv        our own daily history (date, unit, power). The NRC file only keeps 365 days; ours keeps growing.
  reactor_status.json the latest snapshot: each owner's units, which are down, fleet % running.
"""
import csv, datetime as dt, io, json, os, urllib.request
from collections import defaultdict

import desk_memory

ROOT = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(ROOT, "memory", "intel")
HIST, STATUS = os.path.join(DIR, "reactors.csv"), os.path.join(DIR, "reactor_status.json")
URL = ("https://www.nrc.gov/documents-reports/document-collections/events-reports-associated-with/"
       "power-reactor-status-reports/PowerReactorStatusForLast365Days.txt")

# Units each public company in our lineup owns or operates (operator = who books most of the output).
OWNERS = {
    "CEG": ["Braidwood 1", "Braidwood 2", "Byron 1", "Byron 2", "Calvert Cliffs 1", "Calvert Cliffs 2", "Clinton",
            "Dresden 2", "Dresden 3", "FitzPatrick", "Ginna", "LaSalle 1", "LaSalle 2", "Limerick 1", "Limerick 2",
            "Nine Mile Point 1", "Nine Mile Point 2", "Peach Bottom 2", "Peach Bottom 3", "Quad Cities 1",
            "Quad Cities 2", "Salem 1", "Salem 2", "South Texas 1", "South Texas 2"],
    "VST": ["Comanche Peak 1", "Comanche Peak 2", "Beaver Valley 1", "Beaver Valley 2", "Davis-Besse", "Perry 1"],
    "TLN": ["Susquehanna 1", "Susquehanna 2"],
}
UNIT_OWNER = {u: t for t, us in OWNERS.items() for u in us}
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
           "Accept": "text/plain,text/html;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
DOWN_FROM, DOWN_TO = 80, 30      # an outage: was >= 80% and is now <= 30%
BACK_AT = 80                     # back in service at >= 80%


def fetch():
    req = urllib.request.Request(URL, headers=HEADERS)
    txt = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "ignore")
    rows = []
    for line in txt.splitlines()[1:]:
        p = line.split("|")
        if len(p) != 3:
            continue
        try:
            d = dt.datetime.strptime(p[0].split()[0], "%m/%d/%Y").date()
            rows.append((str(d), p[1].strip(), int(p[2])))
        except ValueError:
            continue
    return rows


def fetch_year(y):
    url = URL.replace("PowerReactorStatusForLast365Days.txt", f"{y}/{y}PowerStatus.txt")
    req = urllib.request.Request(url, headers=HEADERS)
    txt = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")
    rows = []
    for line in txt.splitlines()[1:]:
        p = line.split("|")
        if len(p) == 3 and p[1].strip() in UNIT_OWNER:  # keep the archive small: only units our stocks own
            try:
                rows.append((str(dt.datetime.strptime(p[0].split()[0], "%m/%d/%Y").date()), p[1].strip(), int(p[2])))
            except ValueError:
                pass
    return rows


# Owner's stock must have been trading: CEG spun off from Exelon 2022-02-02, TLN relisted 2023-07-03.
LISTED = {"CEG": "2022-02-02", "VST": "2019-01-01", "TLN": "2023-07-03"}


def backfill(first_year=2019):
    """One-time: years of daily power for our owners' units, and every outage since, into desk memory."""
    h = _load_hist()
    for y in range(first_year, dt.date.today().year):
        for d, u, p in fetch_year(y):
            h.setdefault((d, u), p)
    for d, u, p in fetch():  # this year too, so tomorrow's run only sees what's truly new
        if u in UNIT_OWNER:
            h[(d, u)] = p
    _save_hist(h)
    n = 0
    for o in outages(series(h)):
        if o["start"] >= LISTED[o["owner"]]:
            desk_memory.add_event(o["owner"], f"Reactor offline: {o['unit']} ({o['owner']}) dropped to low power",
                                  "reactor_outage", o["start"], "NRC daily power (backfill)")
            n += 1
    return n


def _load_hist():
    try:
        return {(r[0], r[1]): int(r[2]) for r in csv.reader(open(HIST)) if r and r[0] != "date"}
    except FileNotFoundError:
        return {}


def _save_hist(h):
    os.makedirs(DIR, exist_ok=True)
    with open(HIST, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "unit", "power"])
        for (d, u), p in sorted(h.items()):
            w.writerow([d, u, p])


def series(h):
    s = defaultdict(list)
    for (d, u), p in sorted(h.items()):
        s[u].append((d, p))
    return s


def outages(s):
    """Every outage for our owners' units: start date, end date (or None if still down), days down, kind."""
    out = []
    for u, rows in s.items():
        if u not in UNIT_OWNER:
            continue
        start, prev = None, None
        for d, p in rows:
            if start is None and prev is not None and prev >= DOWN_FROM and p <= DOWN_TO:
                start, first = d, p
            elif start is not None and p >= BACK_AT:
                days = (dt.date.fromisoformat(d) - dt.date.fromisoformat(start)).days
                out.append({"unit": u, "owner": UNIT_OWNER[u], "start": start, "end": d, "days": days})
                start = None
            prev = p
        if start is not None:
            days = (dt.date.fromisoformat(rows[-1][0]) - dt.date.fromisoformat(start)).days
            out.append({"unit": u, "owner": UNIT_OWNER[u], "start": start, "end": None, "days": days})
    for o in out:  # refueling outages run ~3-6 weeks and are planned; trips are short and surprise the market
        o["kind"] = "refuel_or_long" if o["days"] >= 18 else ("trip_short" if o["end"] else "open")
    return sorted(out, key=lambda o: o["start"])


def status(s):
    last = max(d for rows in s.values() for d, _ in rows)
    snap = {"date": last, "owners": {}}
    for t, us in OWNERS.items():
        now = {u: dict(s.get(u, [])).get(last) for u in us}
        down = sorted(u for u, p in now.items() if p is not None and p <= DOWN_TO)
        known = [p for p in now.values() if p is not None]
        snap["owners"][t] = {"units": len(us), "down": down, "fleet_running_pct": round(sum(known) / max(1, len(known)), 1)}
    return snap


def run(record_events=True):
    """Daily: pull the NRC file, extend our history, log new outages into desk memory. Returns (status, new_outages)."""
    h = _load_hist()
    before = {(o["unit"], o["start"]) for o in outages(series(h))} if h else set()
    rows = fetch()
    for d, u, p in rows:
        if u in UNIT_OWNER:  # archive only the units our stocks own; the whole fleet is summarized below
            h[(d, u)] = p
    _save_hist(h)
    last = max(d for d, _, _ in rows)
    fleet = [p for d, _, p in rows if d == last]
    s = series(h)
    allo = outages(s)
    new = [o for o in allo if (o["unit"], o["start"]) not in before]
    if record_events and before:  # first run without history: use backfill() instead
        for o in new:
            desk_memory.add_event(o["owner"], f"Reactor offline: {o['unit']} ({o['owner']}) dropped to low power",
                                  "reactor_outage", o["start"], "NRC daily power")
    snap = status(s)
    snap["us_fleet_running_pct"] = round(sum(fleet) / max(1, len(fleet)), 1)
    snap["open_outages"] = [o for o in allo if o["end"] is None]
    snap["recent_outages"] = allo[-15:]
    json.dump(snap, open(STATUS, "w"), indent=1)
    fresh = str(dt.date.fromisoformat(snap["date"]) - dt.timedelta(days=3))
    return snap, ([o for o in new if o["start"] >= fresh] if before else [])  # only alert on outages that just started


def digest(snap):
    lines = [f"US fleet running at {snap['us_fleet_running_pct']}% (NRC, {snap['date']})."]
    for t, o in snap["owners"].items():
        lines.append(f"{t}: {o['units'] - len(o['down'])}/{o['units']} units up"
                     + (f", down: {', '.join(o['down'])}" if o["down"] else ""))
    return lines


if __name__ == "__main__":
    snap, new = run()
    print("\n".join(digest(snap)))
    print(len(snap["recent_outages"]), "recent outages;", len(new), "new")
