"""Power deals and fuel policy: the contracts and laws behind our power and fuel stocks.

Power deals: big tech buying nuclear power for data centers (researched Nov 2026). Moves CEG, VST and TLN.
Fuel policy: the US ban on Russian enriched uranium, the biggest long-run driver for Centrus (LEU).
Event study (research/trial_ledger.json: power_deal_events): the jump comes on the announcement day
(dealmaker +8.8% average, rivals +5%); buying after that day's close was a coin flip, and the 2026 deals faded.
"""
import datetime as dt

DEALS = [
    {"date": "2024-03-04", "seller": "TLN", "buyer": "Amazon (AWS)", "what": "AWS buys Talen's data-center campus next to the Susquehanna plant",
     "size_mw": 960, "years": None, "day0_pct": 12.7},
    {"date": "2024-09-20", "seller": "CEG", "buyer": "Microsoft", "what": "20-year deal to restart Three Mile Island Unit 1 (now Crane)",
     "size_mw": 835, "years": 20, "day0_pct": 22.3},
    {"date": "2025-06-03", "seller": "CEG", "buyer": "Meta", "what": "20-year deal for all of the Clinton plant (Illinois) from June 2027, plus a 30 MW uprate",
     "size_mw": 1121, "years": 20, "day0_pct": -0.1},
    {"date": "2025-06-11", "seller": "TLN", "buyer": "Amazon (AWS)", "what": "Up to 1,920 MW of Susquehanna's output for at least 16 years (through the grid)",
     "size_mw": 1920, "years": 16, "day0_pct": 7.7},
    {"date": "2026-01-09", "seller": "VST", "buyer": "Meta", "what": "20-year deals for 2,176 MW from Perry and Davis-Besse plus 433 MW of uprates; "
     "same day Meta also backed Oklo (1.2 GW campus in Ohio) and TerraPower", "size_mw": 2609, "years": 20, "day0_pct": 10.5,
     "also": ["OKLO"]},
    {"date": "2026-09-30", "seller": "CEG", "buyer": "Amazon", "what": "690 MW from Calvert Cliffs (Maryland), including a 190 MW uprate due 2030-32",
     "size_mw": 690, "years": 20, "day0_pct": -4.0},
    {"date": "2026-10-06", "seller": "CEG", "buyer": "Google", "what": "20-year deal for 890 MW of uprates at 11 reactors plus 15-year supply of 2,700 MW in PJM",
     "size_mw": 3590, "years": 20, "day0_pct": 12.2},
]
WATCH = ["Constellation's Quad Cities reactors come up for relicensing in 2029 and 2031: a likely next deal (analysts' view).",
         "Power bills in the PJM region rose as data centers grew; politics on who pays is the main risk to new deals.",
         "Constellation's 'Peak+' program (first deal 270 MW, 20 years, from 2028) ties nuclear to new power plants."]

HISTORY = ("Past deals: the stock that signed jumped +8.8% on average on the day (median +10.5%) and its rivals +5%. "
           "Buying after the day's close was a coin flip: 5 days later -7% to +18%, and the 2026 deals were lower 20 days later. "
           "7 deals only: context, not a rule.")

POLICY = [
    {"item": "US ban on Russian enriched uranium", "status": "In force since Aug 11 2024 and lasts until the end of 2040. "
     "Waivers (exceptions) are only allowed until Jan 1 2028.", "tickers": ["LEU", "CCJ"],
     "why": "Russia supplied about a fifth of the enriched uranium US reactors use. From 2028 that has to come from somewhere else."},
    {"item": "Centrus (LEU) waivers", "status": "Centrus has waivers for all deliveries already promised to US customers in 2026 and 2027. "
     "Well over half of what it delivers through 2027 comes from Russia's Tenex.", "tickers": ["LEU"],
     "why": "2028 cuts both ways for Centrus: its cheap Russian supply ends, but demand for US-made enrichment rises."},
    {"item": "Russia's own export limit", "status": "Since Nov 2024 Tenex needs a separate Russian export licence for each shipment to the US; "
     "extended through Dec 31 2027.", "tickers": ["LEU"], "why": "Russia can stop shipments early at any time, which would hit Centrus before 2028."},
]

KEYWORDS = ("power purchase agreement", " ppa", "data center", "data centre", "hyperscaler", "uprate", "colocat", "co-locat",
            "russian uranium", "russian enriched", "tenex", "uranium import", "enrichment capacity", "waiver")
SELLERS = {"constellation": "CEG", "vistra": "VST", "talen": "TLN", "oklo": "OKLO", "centrus": "LEU", "nuscale": "SMR"}
BUYERS = ("microsoft", "amazon", "aws", "google", "alphabet", "meta", "oracle", "openai", "apple", "nvidia", "xai")


def is_deal_news(text):
    t = (text or "").lower()
    if any(k in t for k in ("russian uranium", "russian enriched", "tenex", "uranium import")) or \
            ("russia" in t and any(k in t for k in ("enriched uranium", "centrus", "enrichment", "nuclear fuel"))):
        return "policy"
    seller = any(s in t for s in SELLERS)
    if seller and (any(b in t for b in BUYERS) or any(k in t for k in KEYWORDS[:6])) and any(w in t for w in ("deal", "agreement", "contract", "sign", "ppa", "supply")):
        return "deal"
    return None


def tickers_for(text):
    t = (text or "").lower()
    out = [v for k, v in SELLERS.items() if k in t]
    return out or ["CEG", "VST", "TLN"]


def for_ticker(t):
    """Deals and policy for one stock's file."""
    ds = [d for d in DEALS if d["seller"] == t or t in d.get("also", [])]
    rivals = [d for d in DEALS if d["seller"] != t and d["seller"] in ("CEG", "VST", "TLN")] if t in ("CEG", "VST", "TLN") else []
    pol = [p for p in POLICY if t in p["tickers"]]
    if not (ds or rivals or pol):
        return None
    return {"its_power_deals": ds, "rivals_deals": [f"{d['date']}: {d['seller']} with {d['buyer']}, {d['size_mw']} MW" for d in rivals],
            "how_stocks_reacted_to_deals": HISTORY, "fuel_policy": pol, "watch": WATCH if t in ("CEG", "VST", "TLN") else []}


def summary():
    return {"deals": DEALS[::-1], "history": HISTORY, "watch": WATCH, "policy": POLICY,
            "mw_signed_since_2024": sum(d["size_mw"] for d in DEALS)}
