"""Recent-era practice book: rules that made money 2019-2026 but failed 2008-2018 (research/trial_ledger.json:
strategy_sweep_2026_11, holidays_quarters_earnings, idle_cash_regime). The owner's view is that the AI-era nuclear market
is different from the old one; if he's right these rules will keep working live, and this book is the evidence.

No money. Every evening after the close it opens and closes virtual trades at closing prices (0.2% costs), and scores
each rule against the S&P over the same days. A rule becomes a promotion candidate after 30 closed trades if it beat
the S&P on average with t >= 1.5 (and it still has to pass the normal gate before real money)."""
import json, os, datetime as dt
import numpy as np

PATH = "memory/recent_book.json"
COST = 0.002
RULES = {
    "rsi2_dip": "RSI(2) under 10 on one of our 10: buy the close, sell when RSI(2) goes over 70 or after 10 sessions (2019-26: 20.7%/yr)",
    "worst_week": "Our 2 worst stocks over the last 5 days: buy the close, sell after 5 sessions (2019-26: 22.4%/yr, -62% worst drop)",
    "four_down": "4 down closes in a row (our 10 + related stocks): buy the close, sell after 5 sessions (2019-26: 26.2%/yr on related)",
    "quarter_turn": "Buy our 10 at a quarter's last close, sell 3 sessions later (2019-26: +1.56% vs S&P)",
    "momentum_switch": "Each month hold our 10 instead of the S&P when their 12-month return beats the S&P's (2019-26: 41.2%/yr)",
    "ai_scare": "NVIDIA down 6%+ in a day: buy the power trio (CEG, VST, TLN) at the close, sell after 10 sessions (one data point per "
                "scare: 2008-18 -1.0% vs S&P, 2019-26 +2.0% (t 1.6); 2024 +4.5%, 2025 +9.6%, 2026 +12.0%: an AI-era-only pattern)",
}


def _load():
    try:
        return json.load(open(PATH))
    except Exception:
        return {"open": [], "closed": [], "switch": {"in_nuclear": False, "months": []}, "last_run": None}


def _save(b):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    json.dump(b, open(PATH, "w"), indent=1)


def _rsi2(c):
    d = c.diff()
    up, dn = d.clip(lower=0).ewm(alpha=0.5).mean(), (-d.clip(upper=0)).ewm(alpha=0.5).mean()
    return 100 - 100 / (1 + up / dn)


def run(lineup, related, today=None):
    """Call once after the close (prices final). Returns a short list of what happened."""
    import yfinance as yf
    import pandas as pd
    today = today or dt.date.today()
    b = _load()
    if b.get("last_run") == str(today):
        return []
    names = list(dict.fromkeys(list(lineup) + list(related) + ["SPY", "NVDA", "CEG", "VST", "TLN"]))
    raw = yf.download(names, period="14mo", auto_adjust=True, progress=False)
    C, V = raw["Close"], raw["Volume"]
    if C.index[-1].date() != today:
        return []  # no final bar for today yet
    b["last_run"] = str(today)
    spy = float(C["SPY"].iloc[-1])
    ok = lambda t: t in C and C[t].notna().iloc[-1] and float(C[t].iloc[-1]) > 3 and float((C[t] * V[t]).tail(20).mean()) > 5e6
    out = []
    # exits
    still = []
    for p in b["open"]:
        t = p["t"]
        if t not in C or np.isnan(C[t].iloc[-1]):
            still.append(p); continue
        p["days"] += 1
        px = float(C[t].iloc[-1])
        done = p["days"] >= p["hold"]
        if p["rule"] == "rsi2_dip":
            done = done or float(_rsi2(C[t].dropna()).iloc[-1]) > 70
        if done:
            r = px / p["px"] - 1 - COST
            b["closed"].append({**p, "exit_date": str(today), "exit_px": round(px, 2), "ret": round(r * 100, 2),
                                "vs_spy": round((r - (spy / p["spy"] - 1)) * 100, 2)})
            out.append(f"{p['rule']}: closed {t} {r * 100:+.1f}%")
        else:
            still.append(p)
    b["open"] = still
    held = {(p["rule"], p["t"]) for p in b["open"]}

    def enter(rule, t, hold):
        if (rule, t) in held or not ok(t):
            return
        b["open"].append({"rule": rule, "t": t, "date": str(today), "px": round(float(C[t].iloc[-1]), 4), "spy": spy, "hold": hold, "days": 0})
        held.add((rule, t))
        out.append(f"{rule}: opened {t}")
    for t in lineup:
        if t in C and len(C[t].dropna()) > 30 and float(_rsi2(C[t].dropna()).iloc[-1]) < 10:
            enter("rsi2_dip", t, 10)
    r5 = {t: float(C[t].iloc[-1] / C[t].iloc[-6] - 1) for t in lineup if t in C and len(C[t].dropna()) > 6}
    for t in sorted(r5, key=r5.get)[:2]:
        enter("worst_week", t, 5)
    for t in names:
        if t != "SPY" and t in C and len(C[t].dropna()) > 6 and (C[t].dropna().diff().tail(4) < 0).all():
            enter("four_down", t, 5)
    if "NVDA" in C and len(C["NVDA"].dropna()) > 2 and float(C["NVDA"].iloc[-1] / C["NVDA"].iloc[-2] - 1) <= -0.06:
        for t in ("CEG", "VST", "TLN"):
            enter("ai_scare", t, 10)
    nxt = today + dt.timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += dt.timedelta(days=1)
    if nxt.month != today.month and today.month in (3, 6, 9, 12):
        for t in lineup:
            enter("quarter_turn", t, 3)
    # monthly switch: score last month, decide next month
    sw = b["switch"]
    if nxt.month != today.month or not sw.get("decided"):
        basket = (C[[t for t in lineup if t in C]].pct_change().mean(axis=1) + 1).cumprod()
        month_ret_b = float(basket.iloc[-1] / basket[basket.index < f"{today:%Y-%m}-01"].iloc[-1] - 1)
        month_ret_s = float(C["SPY"].iloc[-1] / C["SPY"][C.index < f"{today:%Y-%m}-01"].iloc[-1] - 1)
        if sw.get("decided") and nxt.month != today.month:
            sw["months"].append({"month": f"{today:%Y-%m}", "in_nuclear": sw["in_nuclear"],
                                 "vs_spy": round(((month_ret_b - month_ret_s) if sw["in_nuclear"] else 0) * 100, 2)})
        sw["in_nuclear"] = bool(float(basket.iloc[-1] / basket.iloc[-253] - 1) > float(C["SPY"].iloc[-1] / C["SPY"].iloc[-253] - 1))
        sw["decided"] = str(today)
        out.append(f"momentum_switch: next month {'our 10' if sw['in_nuclear'] else 'the S&P'}")
    b["closed"] = b["closed"][-2000:]
    _save(b)
    return out


def summary():
    b = _load()
    rows = {}
    for rule, desc in RULES.items():
        if rule == "momentum_switch":
            m = b["switch"]["months"]
            x = [r["vs_spy"] for r in m]
            rows[rule] = {"what": desc, "closed": len(m), "open": 1 if b["switch"].get("in_nuclear") else 0,
                          "avg_vs_spy_pct": round(float(np.mean(x)), 2) if x else None, "now": "our 10" if b["switch"].get("in_nuclear") else "S&P"}
            continue
        cl = [r for r in b["closed"] if r["rule"] == rule]
        x = np.array([r["vs_spy"] for r in cl]) if cl else np.array([])
        t = float(x.mean() / x.std() * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else None
        rows[rule] = {"what": desc, "closed": len(cl), "open": sum(1 for p in b["open"] if p["rule"] == rule),
                      "avg_pct": round(float(np.mean([r["ret"] for r in cl])), 2) if cl else None,
                      "avg_vs_spy_pct": round(float(x.mean()), 2) if len(x) else None,
                      "win_pct": round(float(np.mean([r["ret"] > 0 for r in cl])) * 100) if cl else None,
                      "t": round(t, 1) if t is not None else None,
                      "candidate": bool(len(x) >= 30 and x.mean() > 0 and (t or 0) >= 1.5)}
    return {"started": min([p["date"] for p in b["open"]] + [r["date"] for r in b["closed"]], default=None), "rules": rows}
