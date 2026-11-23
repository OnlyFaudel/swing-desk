"""Sprott Physical Uranium Trust watch: market price vs net asset value (premium/discount), pounds held, units.

Why it matters: the trust can only raise money and buy uranium when its units trade ABOVE their asset value (a premium).
Then it buys physical uranium, which lifts the spot price and the miners. Deep discounts mean investors are dumping
uranium exposure. First check (monthly proxy, Jul 2021-Oct 2026, small sample): months where the premium rose 3+ points,
miners' next month +6.2% (11 months); premium falling 3+ points, -0.8% (20). Not traded on yet; collected daily.
"""
import json, os, re, datetime as dt, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, "memory", "intel", "sput.json")
URL = "https://sprott.com/investment-strategies/physical-commodity-funds/uranium/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def _num(pat, txt):
    m = re.search(pat, txt, re.S | re.I)
    return float(m.group(1).replace(",", "")) if m else None


def fetch():
    html = urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=30).read().decode("utf-8", "ignore")
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = re.sub(r"\s+", " ", txt)
    return {"nav": _num(r"NAV\s*US\$\s*([\d.,]+)", txt), "price": _num(r"Market Price\s*US\$\s*([\d.,]+)", txt),
            "premium_pct": _num(r"Premium\s*/\s*Discount[^\d-]*(-?[\d.]+)\s*%", txt),
            "lbs": _num(r"Total (?:Pounds|lbs)\.?\s*of\s*U3[O0]8[^\d]*([\d,]{6,})", txt),
            "units": _num(r"Units Outstanding\s*([\d,]{6,})", txt),
            "as_of": (re.search(r"As of ([A-Z][a-z]+ \d{1,2}, \d{4})", txt) or [None, None])[1]}


def run():
    hist = load()
    snap = fetch()
    if snap.get("premium_pct") is None and snap.get("nav") and snap.get("price"):
        snap["premium_pct"] = round((snap["price"] / snap["nav"] - 1) * 100, 2)
    snap["date"] = str(dt.date.today())
    if snap.get("nav") and snap.get("units") and snap.get("lbs"):  # what the trust's own books say a pound of uranium is worth today
        snap["implied_spot_usd_lb"] = round(snap["nav"] * snap["units"] / snap["lbs"], 2)
    if snap.get("premium_pct") is not None:
        hist = [h for h in hist if h["date"] != snap["date"]] + [snap]
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        json.dump(hist[-800:], open(PATH, "w"), separators=(",", ":"))
    return snap, hist


def load():
    try:
        return json.load(open(PATH))
    except Exception:
        return []


def spot_momentum(hist=None, days=21):
    """Daily uranium price change over ~a month (21 trading days), from the trust's NAV per pound.
    None until there's a month of daily history."""
    h = [x for x in (hist or load()) if x.get("implied_spot_usd_lb")]
    if len(h) < days + 1:
        return None
    return {"now": h[-1]["implied_spot_usd_lb"], "month_ago": h[-1 - days]["implied_spot_usd_lb"],
            "change_pct": round((h[-1]["implied_spot_usd_lb"] / h[-1 - days]["implied_spot_usd_lb"] - 1) * 100, 2), "as_of": h[-1]["date"]}


def summary(hist=None):
    h = hist or load()
    if not h:
        return None
    last = h[-1]
    wk = [x for x in h if x["date"] <= str(dt.date.fromisoformat(last["date"]) - dt.timedelta(days=7))]
    ch = round(last["premium_pct"] - wk[-1]["premium_pct"], 2) if wk and wk[-1].get("premium_pct") is not None else None
    return {"premium_pct": last.get("premium_pct"), "change_1w_pts": ch, "nav": last.get("nav"), "price": last.get("price"),
            "implied_spot_usd_lb": last.get("implied_spot_usd_lb"), "spot_momentum_1m": spot_momentum(h),
            "pounds_held": last.get("lbs"), "as_of": last.get("as_of") or last["date"],
            "what_it_means": ("At a premium the trust can raise money and buy uranium (supports spot and miners); at a discount it can't, "
                              "and a widening discount means investors are leaving uranium. Rising premium months were followed by "
                              "stronger miner months in a small monthly test (n=11).")}
