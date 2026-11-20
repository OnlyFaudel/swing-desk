"""Learning loop (code). Research basis:
- With a few trades a week, early results are mostly noise: telling a 55% setup from a 45% one takes
  ~190 trades. So each setup's result is shrunk toward a prior worth `prior_trades` trades.
- Strategy momentum is real but slow; self-tuned rules often fail out of sample. So the loop may only
  change how much capital a setup gets (0.5x-1.5x, at most +/-25% per week, never zero) and never the
  risk rules (stops, risk per trade, universe, long-only).
- Post-mortems (agent role 16) classify every closed trade as bad_setup / bad_execution / regime_mismatch /
  news_shock / noise. Only bad_setup and bad_execution count as process problems; noise changes nothing.
"""
import datetime as dt
import math

# prior expectancy per trade, in R (risk units), from this session's backtests
PRIORS = {"patient_level": 0.3}


def r_multiple(tr):
    risk = tr.get("risk_pct") or 1.5
    return tr["ret"] / risk


def update_weights(st, cfg, today):
    c = cfg["learning"]
    w = st.setdefault("setup_mult", {})
    hist = st.setdefault("learning_log", [])
    trades = st["book"]["trades"]
    out = {}
    for setup, prior in PRIORS.items():
        rs = [r_multiple(t) for t in trades if t.get("setup") == setup]
        n = len(rs)
        post = (prior * c["prior_trades"] + sum(rs)) / (c["prior_trades"] + n)  # shrunk expectancy (R)
        sd = (sum((x - sum(rs) / n) ** 2 for x in rs) / (n - 1)) ** 0.5 if n > 2 else None
        # target multiplier: 1 + scaled shrunk edge vs prior, bounded
        target = max(c["min_mult"], min(c["max_mult"], 1 + (post - prior)))
        cur = w.get(setup, 1.0)
        new = max(cur - c["max_weekly_change"], min(cur + c["max_weekly_change"], target))
        new = round(max(c["min_mult"], min(c["max_mult"], new)), 3)
        out[setup] = {"trades": n, "avg_R": round(sum(rs) / n, 3) if n else None, "shrunk_R": round(post, 3),
                      "t_stat": round((sum(rs) / n) / (sd / math.sqrt(n)), 2) if sd else None,
                      "mult_before": cur, "mult_after": new}
        w[setup] = new
    hist.append({"date": str(today), "setups": out})
    del hist[:-52]
    return out


def mult(st, setup):
    return st.get("setup_mult", {}).get(setup, 1.0)
