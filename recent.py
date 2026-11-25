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
    "capitulation": "85%+ of the 115 big US stocks fall on the same day: buy our 10 at the close, sell after 10 sessions "
                    "(one point per day, 5-day gap: 2008-18 -1.44% vs S&P (t -2.6), 2019-26 +2.08% (t 2.6): flipped between eras)",
    "tech_panic": "Chip stocks (SMH) fall 3%+ while the S&P falls less than 2%: buy our 10 that fell 3%+ and sit 15%+ under their "
                  "20-day high, sell at +10% or after 6 sessions (per day: 2008-18 +0.50% (n 9), 2019-26 +2.21% vs S&P (t 1.7); "
                  "with related stocks -2.46% / +1.13%: flipped between eras)",
    "vvix_spike": "VVIX (volatility of the VIX) in its top 5% of the past year: buy our 10 at the close, sell after 10 sessions "
                  "(one point per spike: 2008-18 -2.96% vs S&P (t -2.8), 2019-26 +3.25% (t 2.3): flipped between eras)",
    "ai_scare": "NVIDIA down 6%+ in a day: buy the power trio (CEG, VST, TLN) at the close, sell after 10 sessions (one data point per "
                "scare: 2008-18 -1.0% vs S&P, 2019-26 +2.0% (t 1.6); 2024 +4.5%, 2025 +9.6%, 2026 +12.0%: an AI-era-only pattern)",
    "dry_drop": "Our 10 or a related stock falls 8%+ in 10 sessions while its 10-day volume is 30%+ below its prior 50-day average "
                "(sellers running out): buy the close, sell after 10 sessions (2008-18 -0.45% vs S&P, 2019-26 +2.14% (t 3.3); big US "
                "stocks -0.18% / +0.22%: recent and nuclear-only)",
    "dry_rally": "Our 10 or a related stock rises 8%+ in 10 sessions on volume 30%+ below its prior 50-day average: buy the close, sell after "
                 "10 sessions (2008-18 +0.39%, 2019-26 +1.33% (t 3.3); big US stocks -0.37% / +0.27%: fails the independent check)",
    "tg_week_dip": "Thanksgiving week (Mon-Wed): one of our 10 trades 5%+ under yesterday's close (a resting limit order would fill at "
                   "that price, or at the open if it opens lower): buy, sell at the Black Friday close (2007-18 +7.9%/buy vs -0.4% for the "
                   "same trade in ordinary weeks, 2019-25 +4.5% vs +0.8%; ~600 other stocks +3.5%/+1.9% vs -0.3%/-0.7%; only 14 weeks "
                   "with fills in our 10, t 1.5-2.5: small, so practice first)",
    "holiday_dip": "Any of the 3 sessions before a market holiday: our 10 or a related stock trades 3%+ under yesterday's close (limit fill): "
                   "buy, sell at the first close after the holiday (2007-18 +0.32%/buy vs -0.05% ordinary days, 2019-25 +0.52% vs +0.12%, "
                   "t 2.1/2.4; ~600 other stocks show nothing (+0.02 / -0.17): fails the independent check, nuclear-only)",
    "sprott_issuing": "The Sprott uranium trust is issuing new units (units outstanding up 1%+ in ~20 sessions, i.e. it is raising money to "
                      "buy physical uranium) while the 5 miners are already up 10%+ in 20 sessions: buy CCJ, UEC, DNN, UUUU, NXE, sell after "
                      "20 sessions (2021-26 only: +6.3% vs S&P, n 12, vs +0.4% for the miners' rally alone, n 37; one era, small)",
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


def run(lineup, related, today=None, breadth=None):
    """Call once after the close (prices final). Returns a short list of what happened."""
    import yfinance as yf
    import pandas as pd
    today = today or dt.date.today()
    b = _load()
    if b.get("last_run") == str(today):
        return []
    names = list(dict.fromkeys(list(lineup) + list(related) + ["SPY", "NVDA", "CEG", "VST", "TLN", "SMH", "^VVIX"] + list(breadth or [])))
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
    for t in names:  # price moving on drying-up volume (round 21, 2026-11-25)
        if t in ("SPY", "NVDA", "SMH", "^VVIX") or t in (breadth or []) or t not in C or t not in V:
            continue
        c, v = C[t].dropna(), V[t].reindex(C[t].dropna().index)
        if len(c) < 70:
            continue
        r10, v10, v50 = float(c.iloc[-1] / c.iloc[-11] - 1), float(v.tail(10).mean()), float(v.iloc[-60:-10].mean())
        if v50 > 0 and v10 < 0.7 * v50:
            if r10 <= -0.08:
                enter("dry_drop", t, 10)
            elif r10 >= 0.08:
                enter("dry_rally", t, 10)
    try:  # Sprott trust issuing units (memory/intel/sput.json, collected daily) + miners' rally (round 24, 2026-11-25)
        import sput
        h = [x for x in sput.load() if x.get("units")]
        mn = [t for t in ("CCJ", "UEC", "DNN", "UUUU", "NXE") if t in C and len(C[t].dropna()) > 21]
        if len(h) >= 21 and len(mn) >= 4 and h[-1]["units"] >= h[-21]["units"] * 1.01:
            mret = float(np.mean([C[t].dropna().iloc[-1] / C[t].dropna().iloc[-21] - 1 for t in mn]))
            if mret >= 0.10 and b.get("last_sprott", "") < str(today - dt.timedelta(days=28)):
                b["last_sprott"] = str(today)
                for t in mn:
                    enter("sprott_issuing", t, 20)
    except Exception:
        pass
    try:  # limit-order dip buys before holidays (round 57, 2026-11-25)
        import market
        n_before, d, hol_found = 0, today, None
        for _ in range(10):
            d += dt.timedelta(days=1)
            if d.weekday() >= 5:
                continue
            if market.is_holiday(d):
                hol_found = d; break
            n_before += 1
        O, Lo = raw["Open"], raw["Low"]
        spy_prev = float(C["SPY"].iloc[-2])

        def enter_limit(rule, t, k, hold):
            if (rule, t) in held or t not in C or len(C[t].dropna()) < 3 or not ok(t):
                return
            pc, o, lo = float(C[t].iloc[-2]), float(O[t].iloc[-1]), float(Lo[t].iloc[-1])
            lim = pc * (1 - k)
            if np.isnan(o) or np.isnan(lo) or lo > lim:
                return
            fill = o if o <= lim else lim
            b["open"].append({"rule": rule, "t": t, "date": str(today), "px": round(fill, 4), "spy": spy_prev, "hold": hold, "days": 0})
            held.add((rule, t))
            out.append(f"{rule}: opened {t} at ${fill:.2f}")
        if hol_found and n_before <= 2:
            for t in dict.fromkeys(list(lineup) + list(related)):
                enter_limit("holiday_dip", t, 0.03, n_before + 1)
            if hol_found.month == 11 and hol_found.weekday() == 3 and 22 <= hol_found.day <= 28:  # Thanksgiving
                for t in lineup:
                    enter_limit("tg_week_dip", t, 0.05, n_before + 1)
    except Exception as e:
        out.append(f"holiday dip check failed: {e}"[:120])
    if "NVDA" in C and len(C["NVDA"].dropna()) > 2 and float(C["NVDA"].iloc[-1] / C["NVDA"].iloc[-2] - 1) <= -0.06:
        for t in ("CEG", "VST", "TLN"):
            enter("ai_scare", t, 10)
    if "SMH" in C and "SPY" in C and len(C["SMH"].dropna()) > 2:
        smh_d, spy_d = float(C["SMH"].iloc[-1] / C["SMH"].iloc[-2] - 1), float(C["SPY"].iloc[-1] / C["SPY"].iloc[-2] - 1)
        if smh_d <= -0.03 and spy_d > -0.02:
            for t in lineup:
                c = C[t].dropna() if t in C else None
                if c is not None and len(c) > 21 and float(c.iloc[-1] / c.iloc[-2] - 1) <= -0.03 and float(c.iloc[-1] / c.tail(20).max() - 1) <= -0.15:
                    enter("tech_panic", t, 6)
    if "^VVIX" in C and len(C["^VVIX"].dropna()) > 250 and b.get("last_vvix", "") < str(today - dt.timedelta(days=14)):
        vv = C["^VVIX"].dropna()
        if float(vv.iloc[-1]) >= float(vv.tail(250).quantile(0.95)):
            b["last_vvix"] = str(today)
            for t in lineup:
                enter("vvix_spike", t, 10)
    bl = [t for t in (breadth or []) if t in C and len(C[t].dropna()) > 2]
    if len(bl) >= 50:
        moves = [float(C[t].iloc[-1] / C[t].iloc[-2] - 1) for t in bl if not np.isnan(C[t].iloc[-1]) and not np.isnan(C[t].iloc[-2])]
        if moves and sum(1 for m in moves if m < 0) / len(moves) >= 0.85 and b.get("last_capitulation", "") < str(today - dt.timedelta(days=7)):
            b["last_capitulation"] = str(today)
            for t in lineup:
                enter("capitulation", t, 10)
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
        if rule in ("holiday_dip", "tg_week_dip"):  # dozens of fills on the same day are one bet: score one average per day
            by_day = {}
            for r in cl:
                by_day.setdefault(r["date"], []).append(r["vs_spy"])
            x = np.array([float(np.mean(v)) for v in by_day.values()])
        else:
            x = np.array([r["vs_spy"] for r in cl]) if cl else np.array([])
        t = float(x.mean() / x.std() * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else None
        rows[rule] = {"what": desc, "closed": len(cl), "open": sum(1 for p in b["open"] if p["rule"] == rule),
                      "avg_pct": round(float(np.mean([r["ret"] for r in cl])), 2) if cl else None,
                      "avg_vs_spy_pct": round(float(x.mean()), 2) if len(x) else None,
                      "win_pct": round(float(np.mean([r["ret"] > 0 for r in cl])) * 100) if cl else None,
                      "t": round(t, 1) if t is not None else None,
                      "candidate": bool(len(x) >= 30 and x.mean() > 0 and (t or 0) >= 1.5)}
    return {"started": min([p["date"] for p in b["open"]] + [r["date"] for r in b["closed"]], default=None), "rules": rows}
