"""Options Specialist: bets with puts only on events the research has proven are bearish, and only when the put is
cheap enough for the expected drop to pay for it. Starts as a practice book (real option prices, no money) until its
record earns real paper orders.

Proven so far: share offerings (dilution). 51 past offerings in our stocks: next 5 days avg -4.5%, down 69% of the time;
20 days later 73% were still lower.
"""
import math, datetime as dt, json, os

ROOT = os.path.dirname(os.path.abspath(__file__))
TRIGGERS = {
    "offering_dilution": {"words": ("offering", "424b", "at-the-market", "atm program", "shelf", "private placement", "dilution"),
                          "hold_sessions": 5, "history": "51 past offerings: next 5 days avg -4.5%, down 69% of the time"},
}
MAX_PCT = 10          # of the account per single put (cost of the contracts)
SPREAD_MAX_PCT = 20   # a spread can't lose more than its cost, so it may use a bit more
TAKE_PROFIT = 1.0     # sell when the put is worth 2x what we paid
CUT_AT = 0.5          # or when it has lost half


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_put(S, K, T, iv, r=0.04):
    """Black-Scholes put value (T in years)."""
    if T <= 0 or iv <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + iv * iv / 2) * T) / (iv * math.sqrt(T))
    d2 = d1 - iv * math.sqrt(T)
    return K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)


def history_moves(kind="offering_dilution"):
    """Next-5-day moves after past events of this kind in our stocks (one per stock per month)."""
    ev, seen, out = [], set(), []
    for p in ("events.json", "history_events.json", "archive_events.json"):
        try:
            ev += json.load(open(os.path.join(ROOT, "memory", p)))
        except Exception:
            pass
    for e in ev:
        if e.get("type") != kind or e.get("r5") is None or e.get("ticker") == "_basket":
            continue
        k = (e["ticker"], e["date"][:7])
        if k not in seen:
            seen.add(k); out.append(e["r5"] / 100)
    return out


def quote_put(t, days_min=9, days_max=40):
    """The nearest at-the-money put expiring 9-40 days out, with its real bid/ask and implied volatility."""
    import yfinance as yf
    tk = yf.Ticker(t)
    spot = float(tk.history(period="1d", interval="5m").Close.iloc[-1])
    today = dt.date.today()
    for e in tk.options:
        days = (dt.date.fromisoformat(e) - today).days
        if days < days_min:
            continue
        if days > days_max:
            break
        puts = tk.option_chain(e).puts
        puts = puts[(puts.bid > 0) & (puts.ask > 0)]
        if puts.empty:
            continue
        row = puts.iloc[(puts.strike - spot).abs().argsort()[:1]].iloc[0]
        return {"ticker": t, "spot": round(spot, 2), "contract": row.contractSymbol, "strike": float(row.strike), "expiry": e,
                "days": days, "bid": float(row.bid), "ask": float(row.ask), "iv": float(row.impliedVolatility or 0),
                "open_interest": int(row.openInterest or 0) if row.openInterest == row.openInterest else 0}
    return None


def evaluate(q, moves, hold_days=5):
    """Replay every past post-event move on today's real put price: average result and how often it would have paid."""
    if not q or not moves:
        return None
    T_after = max(q["days"] - hold_days * 7 / 5, 0) / 365
    vals = [bs_put(q["spot"] * (1 + m), q["strike"], T_after, q["iv"]) for m in moves]
    pnl = [(v - q["ask"]) / q["ask"] for v in vals]  # bought at the ask, valued at fair price later (sell near the bid: costs a bit more)
    spread = (q["ask"] - q["bid"]) / q["ask"]
    return {"cost_pct_of_stock": round(q["ask"] / q["spot"] * 100, 2), "spread_pct": round(spread * 100, 1),
            "avg_return_pct": round(sum(pnl) / len(pnl) * 100 - spread * 50, 1), "paid_off_pct": round(sum(p > 0 for p in pnl) / len(pnl) * 100),
            "events_replayed": len(moves), "one_contract_usd": round(q["ask"] * 100, 2)}


def quote_spread(t, days_min=9, days_max=40, width_pcts=(5, 8, 10, 15)):
    """Bear put spreads: buy the at-the-money put, sell a cheaper lower-strike put. Max gain = width - cost; max loss = cost.
    Returns every candidate width with its real cost (buy at the ask, sell at the bid)."""
    import yfinance as yf
    tk = yf.Ticker(t)
    spot = float(tk.history(period="1d", interval="5m").Close.iloc[-1])
    today = dt.date.today()
    for e in tk.options:
        days = (dt.date.fromisoformat(e) - today).days
        if days < days_min:
            continue
        if days > days_max:
            break
        puts = tk.option_chain(e).puts
        puts = puts[(puts.bid > 0) & (puts.ask > 0)].sort_values("strike")
        if len(puts) < 2:
            continue
        out = []
        longs = puts[(puts.strike <= spot * 1.01) & (puts.strike >= spot * 0.94)]  # at the money down to ~6% below
        for _, hi in longs.iterrows():
          for w in width_pcts:
            lows = puts[puts.strike <= hi.strike * (1 - w / 100)]
            if lows.empty:
                continue
            lo = lows.iloc[-1]
            debit = float(hi.ask) - float(lo.bid)
            if debit <= 0:
                continue
            out.append({"ticker": t, "spot": round(spot, 2), "expiry": e, "days": days, "long": hi.contractSymbol, "short": lo.contractSymbol,
                        "k_long": float(hi.strike), "k_short": float(lo.strike), "debit": round(debit, 2),
                        "iv_long": float(hi.impliedVolatility or 0), "iv_short": float(lo.impliedVolatility or 0),
                        "mid_debit": round((float(hi.bid) + float(hi.ask)) / 2 - (float(lo.bid) + float(lo.ask)) / 2, 2)})
        if out:
            return out
    return []


def evaluate_spread(s, moves, hold_days=5):
    """Replay past post-event moves on a real spread: value = long put - short put at fair price after hold_days."""
    T_after = max(s["days"] - hold_days * 7 / 5, 0) / 365
    vals = [bs_put(s["spot"] * (1 + m), s["k_long"], T_after, s["iv_long"]) - bs_put(s["spot"] * (1 + m), s["k_short"], T_after, s["iv_short"])
            for m in moves]
    slip = max(s["debit"] - s["mid_debit"], 0)  # paying the spread again when selling
    pnl = [(v - slip - s["debit"]) / s["debit"] for v in vals]
    return {"one_spread_usd": round(s["debit"] * 100, 2), "max_gain_usd": round((s["k_long"] - s["k_short"] - s["debit"]) * 100, 2),
            "avg_return_pct": round(sum(pnl) / len(pnl) * 100, 1), "paid_off_pct": round(sum(p > 0 for p in pnl) / len(pnl) * 100),
            "events_replayed": len(moves)}


def best_spread(t, moves, max_usd):
    """The spread with the best replayed return that fits the money limit (None if nothing pays after costs)."""
    best = None
    for s in quote_spread(t):
        ev = evaluate_spread(s, moves)
        if ev["one_spread_usd"] <= max_usd and ev["avg_return_pct"] > 0 and (best is None or ev["avg_return_pct"] > best[1]["avg_return_pct"]):
            best = (s, ev)
    return best


def mark_spread(p):
    long_bid = mark(p["long"], p["ticker"], side="bid")
    short_ask = mark(p["short"], p["ticker"], side="ask")
    return None if long_bid is None or short_ask is None else round(long_bid - short_ask, 2)


def is_trigger(titles):
    low = " ".join(titles).lower()
    return [k for k, v in TRIGGERS.items() if any(w in low for w in v["words"])]


def mark(q_contract, t, side="bid"):
    """Today's bid (or ask) for a contract we hold (practice)."""
    import yfinance as yf
    sym = q_contract
    exp = "20" + sym[len(t):len(t) + 6]
    e = f"{exp[:4]}-{exp[4:6]}-{exp[6:8]}"
    ch = yf.Ticker(t).option_chain(e).puts
    row = ch[ch.contractSymbol == sym]
    return float(row[side].iloc[0]) if len(row) else None
