"""Uranium supply-shock watch: spot headlines where a big producer cuts, halts or lowers guidance.

Event study (research/trial_ledger.json: supply_shock_events, 14 events 2016-2026): after a big producer cut,
the OTHER miners averaged +3.0% over 5 days and +9.5% over 20 days, but only 8 of 14 went up, and every 2026
event was negative. So this is an alert with history attached, not a trade rule.
"""
import re

SITES = ("kazatomprom", "cameco", "cigar lake", "mcarthur river", "key lake", "inkai", "budenovskoye", "husab", "rossing",
         "orano", "somair", "arlit", "navoi", "langer heinrich", "paladin", "kazakh", "niger uranium")
ACTIONS = ("cut", "cuts", "reduce", "reduces", "reduction", "lower", "lowers", "lowered", "suspend", "suspends", "suspended",
           "halt", "halts", "halted", "shut", "shutdown", "flood", "flooding", "force majeure", "curtail", "delay", "delays",
           "shortfall", "below guidance", "guidance", "sulfuric acid", "sulphuric acid", "strike", "nationaliz", "export ban")
PROD = ("production", "output", "mine", "mining", "uranium", "supply", "wellfield")

HISTORY = {"events": 14, "other_miners_5d_avg_pct": 3.0, "other_miners_20d_avg_pct": 9.5, "up_after_20d": "8 of 14",
           "note": "All 2026 cut announcements were followed by falls: the market now often reads cuts as weak demand."}

WHO_GAINS = {"kazatomprom": ["CCJ", "NXE", "DNN", "UEC", "URG"], "cameco": ["NXE", "DNN", "UEC", "URG"],
             "orano": ["CCJ", "UEC", "DNN"], "paladin": ["CCJ", "UEC", "DNN"]}


def is_supply_shock(text):
    t = (text or "").lower()
    site = next((s for s in SITES if s in t), None)
    if not site:
        return None
    act = next((a for a in ACTIONS if re.search(r"\b" + re.escape(a), t)), None)
    if not act or not any(p in t for p in PROD):
        return None
    if act == "guidance" and not any(w in t for w in ("lower", "cut", "reduc", "below", "miss")):
        return None
    return {"site": site, "action": act}


def beneficiaries(site, universe=()):
    base = WHO_GAINS.get(site) or ["CCJ", "NXE", "DNN", "UEC"]
    if site in ("cigar lake", "mcarthur river", "key lake", "cameco"):
        base = WHO_GAINS["cameco"]
    return [t for t in base if not universe or t in universe] or base[:3]
