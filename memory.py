"""The desk's long-term memory and the options radar (code).

MEMORY: every material event the desk sees is stored with its type (earnings, policy/tariff, war/geopolitics,
contract, supply, analyst, offering, other) and the stock's price; 1, 5 and 20 trading days later the actual
reaction is filled in. Over months this becomes the desk's own playbook: "the last 9 tariff headlines on CCJ
moved it a median -3% over 5 days". Earnings reactions are bootstrapped from up to 25 years of history.

OPTIONS RADAR (alerts only; the bot never trades options): before each earnings report it compares what the
options market implies (at-the-money straddle) with how much the stock has actually moved on its past
reports. Research (Gao, Xing & Zhang 2018): straddles bought 3 days before earnings returned +3.34% on
average, because implied moves tended to understate real ones. When options look cheap vs the stock's own
history, the owner gets an alert with the costs of a straddle and of a cheaper capped-loss call spread.
"""
import datetime as dt, json, os
import numpy as np
import pandas as pd
import yfinance as yf

ROOT = os.path.dirname(os.path.abspath(__file__))
HIST_PATH = os.path.join(ROOT, "research", "event_history.json")
TYPES = ["earnings", "policy_tariff", "war_geopolitics", "contract_deal", "supply", "analyst", "offering_dilution", "other"]


# ---------------------------------------------------------------- bootstrap earnings history
def bootstrap_earnings(tickers, force=False):
    hist = json.load(open(HIST_PATH)) if os.path.exists(HIST_PATH) else {}
    for t in tickers:
        if t in hist and not force:
            continue
        try:
            ed = yf.Ticker(t).get_earnings_dates(limit=60).index.tz_convert("America/New_York")
            c = yf.download(t, start="2000-01-01", auto_adjust=True, progress=False)["Close"]
            c = c.iloc[:, 0] if hasattr(c, "columns") else c
            moves = []
            for d in ed:
                if d.date() >= dt.date.today():
                    continue
                day = pd.Timestamp(d.date())
                j = c.index.searchsorted(day, side="left" if d.hour < 12 else "right")
                if 0 < j < len(c):
                    m = float(c.iloc[j] / c.iloc[j - 1] - 1)
                    if abs(m) < 0.40:  # bigger "earnings moves" in free data are almost always date/split errors
                        moves.append([str(c.index[j].date()), round(m * 100, 2)])
            moves = sorted({m[0]: m for m in moves}.values())  # oldest -> newest, one per date
            hist[t] = {"earnings_moves_pct": moves}
        except Exception as e:
            hist.setdefault(t, {"earnings_moves_pct": []})["error"] = str(e)[:100]
    os.makedirs(os.path.dirname(HIST_PATH), exist_ok=True)
    json.dump(hist, open(HIST_PATH, "w"), indent=1)
    return hist


def earnings_stats(t):
    hist = json.load(open(HIST_PATH)) if os.path.exists(HIST_PATH) else {}
    m = np.abs([x[1] for x in hist.get(t, {}).get("earnings_moves_pct", [])])
    if len(m) < 6:
        return None
    recent = m[-12:]
    return {"n": int(len(m)), "median_abs_pct": round(float(np.median(m)), 2), "recent12_median_abs_pct": round(float(np.median(recent)), 2),
            "pct_moves_over_5": round(float((m > 5).mean() * 100))}


# ---------------------------------------------------------------- live event memory
def remember(st, item, price):
    mem = st.setdefault("event_memory", [])
    mem.append({"ticker": item["ticker"], "type": item.get("event_type") or "other", "title": item["title"][:140],
                "date": str(dt.date.today()), "price": round(float(price), 2), "materiality": item.get("materiality"),
                "direction_called": item.get("direction"), "r1": None, "r5": None, "r20": None})
    del mem[:-3000]


def fill_reactions(st, data):
    for e in st.get("event_memory", []):
        if e["r20"] is not None or e["ticker"] not in data:
            continue
        after = data[e["ticker"]][data[e["ticker"]].index > e["date"]].Close
        for k, n in (("r1", 1), ("r5", 5), ("r20", 20)):
            if e[k] is None and len(after) >= n:
                e[k] = round((float(after.iloc[n - 1]) / e["price"] - 1) * 100, 2)


def playbook(st, t):
    """What has each type of event done to this stock so far?"""
    out = {}
    for typ in TYPES:
        ev = [e for e in st.get("event_memory", []) if e["ticker"] == t and e["type"] == typ and e["r5"] is not None]
        if ev:
            r5 = [e["r5"] for e in ev]
            out[typ] = {"n": len(ev), "median_5d_pct": round(float(np.median(r5)), 2), "pct_up_5d": round(sum(x > 0 for x in r5) / len(r5) * 100),
                        "direction_calls_right_pct": round(sum((e["direction_called"] == "up") == (e["r5"] > 0) for e in ev
                                                               if e["direction_called"] in ("up", "down")) /
                                                           max(1, sum(e["direction_called"] in ("up", "down") for e in ev)) * 100)}
    es = earnings_stats(t)
    if es:
        out["earnings_history"] = es
    return out


# ---------------------------------------------------------------- options radar
def options_radar(t, price, next_earnings, cfg):
    if not next_earnings:
        return None
    ed = dt.date.fromisoformat(next_earnings)
    days = int(np.busday_count(dt.date.today(), ed))
    if not (0 < days <= cfg["options_radar"]["days_before_earnings"]):
        return None
    es = earnings_stats(t)
    if not es:
        return None
    tk = yf.Ticker(t)
    exps = [e for e in tk.options if dt.date.fromisoformat(e) > ed]
    if not exps:
        return None
    exp = exps[0]
    ch = tk.option_chain(exp)
    k = float(ch.calls.strike.iloc[(ch.calls.strike - price).abs().argsort().iloc[0]])
    mid = lambda df, kk: float(((df[df.strike == kk].bid + df[df.strike == kk].ask) / 2).iloc[0])
    straddle = mid(ch.calls, k) + mid(ch.puts, k)
    implied = straddle / price * 100
    # what history says to expect: the earnings jump plus normal moves for the other days until expiry
    d_exp = int(np.busday_count(dt.date.today(), dt.date.fromisoformat(exp)))
    c = yf.download(t, period="6mo", auto_adjust=True, progress=False)["Close"]
    c = c.iloc[:, 0] if hasattr(c, "columns") else c
    r = c.pct_change().dropna() * 100
    daily_sd = float(1.4826 * np.median(np.abs(r - r.median())))  # robust daily volatility (ignores jump days)
    expected = float(np.sqrt(es["recent12_median_abs_pct"] ** 2 + daily_sd ** 2 * max(d_exp - 1, 0)))
    ratio = implied / expected if expected else None
    # cheaper capped-loss idea: call debit spread from ATM to ATM + historical median move
    up = price * (1 + es["recent12_median_abs_pct"] / 100)
    k2 = float(ch.calls.strike.iloc[(ch.calls.strike - up).abs().argsort().iloc[0]])
    spread = max(0.0, mid(ch.calls, k) - mid(ch.calls, k2)) if k2 > k else None
    return {"ticker": t, "earnings": next_earnings, "expiry": exp, "strike": k, "implied_move_pct": round(implied, 1),
            "history_expected_move_pct": round(expected, 1), "cheapness_ratio": round(ratio, 2) if ratio else None,
            "looks_cheap": bool(ratio and ratio < cfg["options_radar"]["cheap_ratio"]),
            "straddle_cost_usd": round(straddle * 100), "call_spread": f"{k:g}/{k2:g}" if spread else None,
            "call_spread_cost_usd": round(spread * 100) if spread else None,
            "affordable": bool(spread and spread * 100 <= cfg["options_radar"]["max_alert_cost_usd"]),
            "note": "Alert only. Options can expire worthless: the cost is the maximum loss."}
