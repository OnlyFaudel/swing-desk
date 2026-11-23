"""The world view: which countries run, build and plan reactors, and how much uranium each needs (World Nuclear
Association's public table, updated about monthly). The bot keeps every snapshot, so when a country adds reactors to
its plans it becomes an event the discovery engine can test ("China moved 4 reactors to under construction").

memory/intel/world.json: {"snapshots": {date: {country: {...}}}, "updated_label": "..."}
"""
import datetime as dt, io, json, os, re, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, "memory", "intel", "world.json")
URL = "https://world-nuclear.org/information-library/facts-and-figures/world-nuclear-power-reactors-and-uranium-requireme"
COLS = ["twh", "share_pct", "operable", "operable_mw", "building", "building_mw", "planned", "planned_mw", "proposed", "proposed_mw", "uranium_t"]


def _num(x):
    try:
        return float(str(x).replace(",", "").replace("c.", "").replace("%", "").strip())
    except ValueError:
        return None


def fetch():
    import pandas as pd
    h = urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 SwingDesk research"}), timeout=40).read().decode("utf-8", "ignore")
    t = pd.read_html(io.StringIO(h))[0]
    rows = {}
    for _, r in t.iterrows():
        name = re.sub(r"[†*‡]|&nbsp;", "", str(r.iloc[0])).strip()
        if not name or name.lower() == "nan" or name.upper() == "COUNTRY":
            continue
        vals = [_num(v) for v in list(r.iloc[1:12])]
        if all(v is None for v in vals):
            continue
        rows["World" if name.upper().startswith("WORLD") else name] = dict(zip(COLS, vals))
    m = re.search(r"Updated[^<]{0,60}", h)
    return rows, (m.group(0).strip() if m else "")


def run():
    """Weekly: new snapshot; any change in a country's building/planned counts becomes a sector event."""
    import archive
    db = json.load(open(PATH)) if os.path.exists(PATH) else {"snapshots": {}}
    rows, label = fetch()
    today = str(dt.date.today())
    prev = db["snapshots"][max(db["snapshots"])] if db["snapshots"] else None
    changes = []
    if prev:
        for c, r in rows.items():
            p = prev.get(c) or {}
            for k, word in (("building", "under construction"), ("planned", "planned"), ("proposed", "proposed"), ("operable", "running")):
                a, b = p.get(k) or 0, r.get(k) or 0
                if c != "World" and a != b:
                    changes.append({"country": c, "what": word, "from": a, "to": b})
    if not prev or rows != prev:
        db["snapshots"][today] = rows
    db["updated_label"] = label
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    json.dump(db, open(PATH, "w"), separators=(",", ":"))
    if changes:  # into the sector event file for the discovery engine
        ev = archive._load(archive.EVENTS, [])
        for ch in changes:
            up = ch["to"] > ch["from"]
            ev.append({"ticker": "_basket", "date": today, "title": f"{ch['country']}: reactors {ch['what']} {ch['from']:.0f} -> {ch['to']:.0f}",
                       "type": f"world_{'more' if up else 'fewer'}_{ch['what'].replace(' ', '_')}", "source": "World Nuclear Association",
                       "r0": None, "r1": None, "r5": None, "r20": None, "r60": None, "x5": None, "x20": None})
        archive._save(archive.EVENTS, ev)
    return summary(db), changes


def summary(db=None, k=15):
    db = db or (json.load(open(PATH)) if os.path.exists(PATH) else {"snapshots": {}})
    if not db["snapshots"]:
        return {}
    rows = db["snapshots"][max(db["snapshots"])]
    ctry = {c: r for c, r in rows.items() if c != "World"}
    pipe = lambda r: (r.get("building_mw") or 0) + (r.get("planned_mw") or 0) + (r.get("proposed_mw") or 0)
    return {"source": f"World Nuclear Association ({db.get('updated_label', '')})", "world": rows.get("World"),
            "most_uranium_needed": [{"country": c, "tonnes_u_per_year": r.get("uranium_t"), "reactors_running": r.get("operable"),
                                     "share_of_power_pct": r.get("share_pct")} for c, r in sorted(ctry.items(), key=lambda kv: -(kv[1].get("uranium_t") or 0))[:k]],
            "biggest_build_pipelines": [{"country": c, "building": r.get("building"), "planned": r.get("planned"), "proposed": r.get("proposed"),
                                         "pipeline_mw": pipe(r), "vs_running_now": round(pipe(r) / r["operable_mw"], 2) if r.get("operable_mw") else "new to nuclear"}
                                        for c, r in sorted(ctry.items(), key=lambda kv: -pipe(kv[1]))[:k]],
            "newcomers": [c for c, r in ctry.items() if not r.get("operable") and ((r.get("building") or 0) + (r.get("planned") or 0)) > 0],
            "snapshots_kept": len(db["snapshots"])}


if __name__ == "__main__":
    s, ch = run()
    print(json.dumps(s, indent=1)[:2500]); print(ch[:10])
