"""Nuclear license tracker: where each new reactor project stands with the NRC and what comes next.

Hand-kept list (researched Nov 2026). The collector flags new licensing headlines; shocks.py posts them.
Dates are only filled in when a real date is known; otherwise `window` says roughly when.
"""
import datetime as dt

NRC_RULE = "NRC must now decide on new reactor applications within 18 months (2025 rules)."

PROJECTS = [
    {"project": "Natrium, Kemmerer Unit 1 (Wyoming)", "company": "TerraPower (private) with GE Vernova Hitachi",
     "tickers": ["GEV", "LEU"], "status": "Construction permit issued March 2026 (first for a non-light-water power reactor).",
     "next": "Building; operating license application later", "window": "operation around 2030-31",
     "why_it_matters": "Needs HALEU fuel, which mostly means Centrus (LEU). GE Vernova supplies the design."},
    {"project": "Long Mott (Seadrift, Texas)", "company": "X-energy (private) and Dow", "tickers": ["LEU", "OKLO", "SMR", "NNE"],
     "status": "Construction permit issued Nov 9 2026: first for a high-temperature gas reactor in nearly 60 years.",
     "next": "Construction; operating license review", "window": "early 2030s",
     "why_it_matters": "Proof the NRC can license advanced designs quickly. Read-through for every small-reactor stock."},
    {"project": "Palisades restart (Michigan)", "company": "Holtec (private)", "tickers": ["CEG", "VST", "TLN"],
     "status": "NRC approved a key license amendment Oct 14 2026.", "next": "Return to service", "window": "2027",
     "why_it_matters": "First US plant restarted after shutdown; sets the template for other restarts (like Constellation's Crane)."},
    {"project": "Palisades SMR-300 (two units)", "company": "Holtec (private)", "tickers": ["SMR", "OKLO"],
     "status": "Partial construction permit application accepted Feb 2026; safety analysis report filed Sept 2026.",
     "next": "NRC construction permit decision", "window": "2027 (18-month clock)",
     "why_it_matters": "Competes with NuScale (SMR) for the same small-reactor customers."},
    {"project": "AP1000 design certification update", "company": "Westinghouse (49% owned by Cameco)", "tickers": ["CCJ", "BWXT"],
     "status": "NRC updated the AP1000 certification Oct 14 2026.", "next": "New AP1000 orders and construction starts",
     "window": "2027 onward", "why_it_matters": "Each new AP1000 means fuel and services income for Cameco through Westinghouse."},
    {"project": "Aurora powerhouse at Idaho National Lab", "company": "Oklo", "tickers": ["OKLO"],
     "status": "Licensing with the NRC in progress.", "next": "NRC license decision", "window": "company targets operation by 2028",
     "why_it_matters": "Oklo has no revenue yet: licensing news is the main thing that moves it."},
    {"project": "US460 small reactor (77 MW modules)", "company": "NuScale", "tickers": ["SMR"],
     "status": "NRC standard design approval May 2025.", "next": "A customer's construction permit application",
     "window": "depends on a customer (TVA / ENTRA1 plans)", "why_it_matters": "Design is approved; what NuScale lacks is a firm order."},
]

# What licensing news has done to the stocks in 2026 (research/trial_ledger.json: license_events_2026).
HISTORY = ("2026 licensing approvals: first-day moves were mixed (Long Mott permit: small-reactor stocks +7% to +14%; Kemmerer: +0% to +4%) "
           "and most of it was gone within 5 trading days. Only 3 events, so this is context, not a trading rule.")

KEYWORDS = ("construction permit", "operating license", "combined license", "design certification", "design approval",
            "license amendment", "nrc approves", "nrc approved", "nrc accepts", "nrc issues", "license application",
            "early site permit", "license renewal", "restart approval")


def is_license_news(text):
    t = (text or "").lower()
    return any(k in t for k in KEYWORDS)


KEYS = {"Natrium": ("natrium", "kemmerer", "terrapower"), "Long Mott": ("long mott", "x-energy", "seadrift"),
        "Palisades restart": ("palisades",), "Palisades SMR-300": ("smr-300", "holtec"), "AP1000": ("ap1000", "westinghouse"),
        "Aurora": ("oklo", "aurora"), "US460": ("nuscale", "us460")}


def tickers_for(text):
    t = (text or "").lower()
    out = []
    for p in PROJECTS:
        for name, keys in KEYS.items():
            if name.lower() in p["project"].lower() and any(k in t for k in keys):
                out += [x for x in p["tickers"] if x not in out]
    return out or ["OKLO", "SMR", "NNE", "LEU"]


def dated(days=45, today=None):
    """Catalyst-calendar entries for milestones with a known date."""
    today = today or dt.date.today()
    end = str(today + dt.timedelta(days=days))
    return [{"date": p["date"], "ticker": (p["tickers"] or [""])[0], "what": f"{p['project']}: {p['next']}", "kind": "license"}
            for p in PROJECTS if p.get("date") and str(today) <= p["date"] <= end]


def summary():
    return {"rule": NRC_RULE, "history": HISTORY,
            "projects": [{k: p.get(k) for k in ("project", "company", "tickers", "status", "next", "window", "why_it_matters")} for p in PROJECTS]}
