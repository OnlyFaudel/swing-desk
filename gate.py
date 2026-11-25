"""Promotion gate (code). The owner's research standard applied to the bot's OWN results:
real money buys only after the paper record passes, judged on risk-adjusted, net-of-cost evidence,
never on raw return targets.

Pass requires ALL of:
  - Deflated Sharpe Ratio >= min_dsr (Bailey & Lopez de Prado 2014), with N = every variant ever backtested
    (research/trial_ledger.json) and that research's cross-trial Sharpe variance: the more ideas were tried,
    the higher the bar
  - net-of-cost return > 0 in both halves of the record, on the HONEST equity curve (real costs charged,
    touch-only support fills removed: see honest_equity)
  - max drawdown no worse than max_drawdown_pct
  - at least min_days trading days of record
"""
import json, os
import numpy as np
from scipy.stats import norm, skew, kurtosis

ROOT = os.path.dirname(os.path.abspath(__file__))
G = 0.5772156649


def honest_equity(st):
    """The paper equity curve minus what real fills would have cost: every closed trade's real-world spread/slippage
    (realistic_cost), support buys whose fill only touched the price removed entirely, and 0.5% off target sells
    that only touched (research 2026-11-23: touch-only fills carried most of the support buys' paper edge)."""
    eqs = st["book"].get("equity", [])
    hair = []
    for r in st["book"].get("trades", []):
        d = str(r.get("exit_time") or "")[:10]
        h = r.get("realistic_cost", 0) or 0
        if r.get("entry_fill") == "touch-only":
            h = r["pnl"]  # the order most likely would not have filled: no profit, no loss
        elif r.get("exit_fill") == "touch-only":
            h += r.get("dollars", 0) * 0.005
        if d and h:
            hair.append((d, h))
    out = []
    for e in eqs:
        cut = sum(h for d, h in hair if d <= str(e[0])[:10])
        out.append(e[1] - cut)
    return np.array(out, dtype=float)


def evaluate(st, cfg):
    c = cfg["promotion_gate"]
    allled = json.load(open(os.path.join(ROOT, "research", "trial_ledger.json")))["strategies"]
    led = dict(allled[c["strategy"]])
    # the account trades every adopted rule, and every idea ever tried anywhere was a chance to get lucky: count them all
    # (was: only the strategy's own 30 trials, which set the luck hurdle far too low)
    led["trials"] = max(int(led.get("trials") or 1), sum(int(v.get("trials") or 0) for v in allled.values() if isinstance(v, dict)))
    eq = honest_equity(st)  # judged on honest fills, not paper ones
    out = {"days": int(len(eq)), "trials": led["trials"], "min_days": c["min_days"], "passed": False}
    if len(eq) < 3:
        out["reason"] = "not enough record yet"
        return out
    r = np.diff(eq) / eq[:-1]
    n, N, V = len(r), led["trials"], led.get("sr_var_daily") or 1e-4
    sr0 = np.sqrt(V) * ((1 - G) * norm.ppf(1 - 1 / N) + G * norm.ppf(1 - 1 / (N * np.e)))
    sd = r.std(ddof=1)
    sr = r.mean() / sd if sd > 0 else 0.0
    sk = float(skew(r)) if n > 3 and sd > 0 else 0.0
    ku = float(kurtosis(r, fisher=False)) if n > 3 and sd > 0 else 3.0
    den = max(1e-9, 1 - sk * sr + (ku - 1) / 4 * sr ** 2)
    dsr = float(norm.cdf((sr - sr0) * np.sqrt(n - 1) / np.sqrt(den))) if n > 1 else 0.0
    half = len(eq) // 2
    h1, h2 = eq[half] / eq[0] - 1, eq[-1] / eq[half] - 1
    mdd = float((eq / np.maximum.accumulate(eq) - 1).min() * 100)
    checks = {"dsr": dsr >= c["min_dsr"], "both_halves_positive": h1 > 0 and h2 > 0,
              "drawdown": mdd >= c["max_drawdown_pct"], "enough_days": len(eq) >= c["min_days"]}
    out.update(dsr=round(dsr, 3), hurdle_sharpe_ann=round(float(sr0 * np.sqrt(252)), 2), sharpe_ann=round(float(sr * np.sqrt(252)), 2),
               half1_pct=round(h1 * 100, 2), half2_pct=round(h2 * 100, 2), maxdd_pct=round(mdd, 1), checks=checks,
               passed=all(checks.values()),
               reason="passed" if all(checks.values()) else "failing: " + ", ".join(k for k, v in checks.items() if not v))
    return out


def live_entries_allowed(st, cfg, broker_name):
    """Real-money buys need a passed gate (or the owner's explicit override). Paper/sim always allowed."""
    if not broker_name.endswith("LIVE") or not cfg["promotion_gate"]["require_for_live"] or cfg.get("live_override"):
        return True
    return bool((st.get("gate") or {}).get("passed"))
