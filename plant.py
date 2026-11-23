"""The Plant Engineer's desk: how nuclear plants and the fuel chain physically work, plus what the plants are doing right now.

Other agents are traders; this seat explains the physical side (outages, refueling, fuel steps, regulators, contracts)
so the team knows WHY something matters, for WHICH company, and for HOW LONG.
"""
import json, os, datetime as dt

ROOT = os.path.dirname(os.path.abspath(__file__))

PRIMER = {
    "fuel_chain": "mine/mill uranium (U3O8, yellowcake) -> conversion to UF6 -> enrichment (measured in SWU; LEU 3-5% U-235, HALEU 5-20% "
                  "for advanced reactors) -> fuel fabrication -> reactor (about 18-24 months per fuel batch) -> spent fuel storage.",
    "who_does_what": {
        "CCJ": "Cameco: mines (Cigar Lake, McArthur River/Key Lake in Saskatchewan), conversion (Port Hope), fuel services; 49% of Westinghouse "
               "(reactor designs AP1000/AP300, fuel, plant services). Sells mostly under long-term contracts.",
        "NXE": "NexGen: developer of Arrow/Rook I (Saskatchewan), not producing yet; moves on permits, financing, construction milestones.",
        "UEC": "Uranium Energy: US in-situ recovery (Wyoming, South Texas), holds physical uranium; very sensitive to spot price.",
        "DNN": "Denison: Wheeler River/Phoenix ISR project (Saskatchewan) plus McClean Lake mill share; developer, permits drive it.",
        "UUUU": "Energy Fuels: White Mesa mill (Utah), US uranium plus rare earths and vanadium; rare-earth news moves it too.",
        "LEU": "Centrus: US enrichment, the only US HALEU producer (Piketon, Ohio) under DOE contracts; also resells Russian/other LEU (import rules matter).",
        "BWXT": "BWX Technologies: naval reactors for the US Navy (subs, carriers), fuel and components, medical isotopes; defense budgets drive it.",
        "CEG": "Constellation: biggest US nuclear fleet (~25 reactors) selling power; data-center deals (Crane/TMI-1 restart for Microsoft).",
        "VST": "Vistra: power company with nuclear (Comanche Peak in Texas, Beaver Valley, Perry, Davis-Besse) plus gas; ERCOT and PJM prices matter.",
        "TLN": "Talen: Susquehanna nuclear plant (Pennsylvania) feeding an Amazon data-center campus; PJM capacity prices matter.",
    },
    "plants": "US reactors run about 90-93% of the time. Refueling outages are planned every 18-24 months, last about 3-6 weeks, cluster in "
              "spring and fall (low demand). An unplanned trip (scram) is usually days; a long unplanned outage costs a power company "
              "lost sales at peak prices (summer heat, winter cold). Reactor power data: NRC daily 'power reactor status'.",
    "power_markets": "PJM (mid-Atlantic/Midwest) runs a yearly capacity auction: high prices = more revenue for CEG/TLN/VST plants there. "
                     "ERCOT (Texas) pays spikes in heat/cold. Data-center power deals (PPAs) lock in high prices for 10-20 years.",
    "regulators": "NRC licenses plants and new designs (construction permits, operating licenses, license renewals to 60-80 years, "
                  "uprates). DOE funds HALEU, loans and restarts. Congress sets bans (Russian uranium imports), tax credits (45U, 45Y).",
    "contracts": "Utilities buy uranium mostly on long-term contracts (term price), not spot. A rising term price helps miners for years; "
                 "spot is the fast, emotional number. Enrichment (SWU) prices are separate and matter for LEU.",
    "how_long_news_matters": "Permits and licenses: months to years (developers NXE/DNN react most). A mine/mill disruption: weeks to "
                             "months, helps other producers. Plant outage: days to weeks, only hurts that owner. Policy/bans: years.",
}


def _load(p, d):
    try:
        return json.load(open(p))
    except Exception:
        return d


def snapshot(st=None):
    """What the plants and fuel chain are doing now, from the data the bot already collects."""
    import reactors, uprice
    snap = _load(reactors.STATUS, {})
    out = {"as_of": snap.get("date"), "us_fleet_running_pct": snap.get("us_fleet_running_pct"),
           "our_owners": snap.get("owners"),
           "open_outages": [{k: o.get(k) for k in ("unit", "owner", "start", "days", "kind")} for o in (snap.get("open_outages") or [])][:10],
           "recent_outages": [{k: o.get(k) for k in ("unit", "owner", "start", "end", "days", "kind")} for o in (snap.get("recent_outages") or [])][-6:],
           "season": _season(), "uranium_price": {k: {"usd_per_lb": v.get("usd_per_lb"), "12m_change_pct": v.get("12m_change_pct")}
                                                   for k, v in (uprice.summary() or {}).items() if isinstance(v, dict)}}
    if st:
        out["plant_news_this_week"] = [f"{i.get('place')}: {i.get('title')}" for i in (st.get("news_feed") or [])[-40:]
                                       if any(w in (i.get("title") or "").lower() for w in
                                              ("reactor", "outage", "nrc", "refuel", "restart", "enrich", "haleu", "mine", "mill", "license", "pjm", "ercot"))][-8:]
    return out


def _season():
    m = dt.date.today().month
    if m in (3, 4, 5, 9, 10, 11):
        return "refueling season (spring/fall): planned outages are normal now and rarely move the stocks"
    if m in (6, 7, 8):
        return "summer peak: an unplanned outage now costs the most (high power prices)"
    return "winter peak: cold snaps lift power prices; unplanned outages cost more than in spring/fall"


def context(st=None):
    return {"how_it_works": PRIMER, "plants_now": snapshot(st)}
