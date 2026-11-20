"""Signals registry, pre-open nowcast and weekly drift monitor (the feedback loop).

Research result (research/ccj_leadlag.py, Nov 2026): Asia's close predicts the US opening GAP for CCJ/TSM/ETN
out-of-sample, but nothing after the open. So the nowcast is information only: it says where the open will
probably land relative to the resting buy and the stop. It never places or sizes a trade by itself.

Registry statuses: research -> shadow -> live -> retired. Only `live` signals may touch orders, and only after the
promotion gate. Every new variant tried anywhere adds to research/trial_ledger.json (it raises the DSR hurdle).
"""
import json, os, datetime as dt
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(HERE, "research", "signals_registry.json")
ASIA = ["^N225", "^KS11", "^HSI", "^AXJO"]


def registry():
    with open(REG) as f:
        return json.load(f)


def _closes(tickers, period="3y"):
    import yfinance as yf
    raw = yf.download(list(tickers), period=period, auto_adjust=True, progress=False)
    out = {}
    for t in tickers:
        try:
            df = raw.xs(t, axis=1, level=1).dropna()
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            out[t] = df
        except KeyError:
            pass
    return out


def asia_composite(D, us_ticker):
    """Standardised Asia close move with the prior US session removed (what Asia added overnight)."""
    us = D[us_ticker].index
    spy_prev = D["SPY"].Close.pct_change().reindex(us).shift(1)
    own_prev = D[us_ticker].Close.pct_change().shift(1)
    zs = []
    for t in ASIA:
        if t not in D:
            continue
        # Asia rows dated after the last US session are today's pre-open info: extend the US index to include them
        idx = us.union(D[t].index[D[t].index > us[-1]][:1])
        a = D[t].Close.pct_change().reindex(idx)
        X = pd.concat([a, spy_prev.reindex(idx).ffill(limit=1), own_prev.reindex(idx)], axis=1)
        if X.index[-1] > us[-1]:  # today's row: prior session = last US session
            X.iloc[-1, 1] = D["SPY"].Close.pct_change().iloc[-1]
            X.iloc[-1, 2] = D[us_ticker].Close.pct_change().iloc[-1]
        fit = X.dropna().iloc[-500:]
        A = np.c_[np.ones(len(fit)), fit.iloc[:, 1:]]
        b = np.linalg.lstsq(A, fit.iloc[:, 0], rcond=None)[0]
        e = X.iloc[:, 0] - np.c_[np.ones(len(X)), X.iloc[:, 1:]] @ b
        zs.append(e / (fit.iloc[:, 0] - A @ b).std())
    return pd.concat(zs, axis=1).mean(axis=1) if zs else pd.Series(dtype=float)


def nowcast(tickers, D=None):
    """Before 9:30 ET: expected opening gap per ticker from Asia's close, with its trailing hit-rate."""
    D = D or _closes(set(tickers) | set(ASIA) | {"SPY"})
    out = {}
    for t in tickers:
        if t not in D:
            continue
        c = D[t]
        gap = c.Open / c.Close.shift(1) - 1
        comp = asia_composite(D, t)
        hist = pd.concat([comp, gap], axis=1).dropna().iloc[-500:]
        if len(hist) < 120:
            continue
        beta = np.polyfit(hist.iloc[:, 0], hist.iloc[:, 1], 1)
        today_z = comp.iloc[-1] if comp.index[-1] > c.index[-1] else np.nan
        corr120 = hist.iloc[-120:].corr().iloc[0, 1]
        out[t] = {"asia_z": None if np.isnan(today_z) else round(float(today_z), 2),
                  "expected_gap_pct": None if np.isnan(today_z) else round(float(np.polyval(beta, today_z)) * 100, 2),
                  "corr_120d": round(float(corr120), 2), "last_close": round(float(c.Close.iloc[-1]), 2)}
    return out


def gap_risk(nc, armed):
    """Flag resting buys whose stop sits inside the expected opening gap (the open would break the level)."""
    flags = {}
    for t, a in armed.items():
        n = nc.get(t) or {}
        g = n.get("expected_gap_pct")
        if g is None:
            continue
        exp_open = n["last_close"] * (1 + g / 100)
        if exp_open <= a["stop"]:
            flags[t] = f"Asia points to an open near ${exp_open:.2f}, at or under the ${a['stop']:.2f} stop"
        elif exp_open <= a["entry"]:
            flags[t] = f"Asia points to an open near ${exp_open:.2f}: the ${a['entry']:.2f} buy likely fills at the open"
    return flags


# ------------------------------------------------------------------ weekly drift monitor
def _rolling_corr(sig, tgt, n):
    m = pd.concat([sig, tgt], axis=1).dropna().iloc[-n:]
    if len(m) < 30:
        return None, len(m)
    return float(m.corr().iloc[0, 1]), len(m)


def strategy_drift(trades, expect):
    """Live/paper trade results vs the backtest's per-trade expectation (one-sided, in R multiples)."""
    import learning
    r = np.array([learning.r_multiple(x) for x in trades if x.get("setup", "patient_level") == "patient_level" and "ret" in x], float)
    if len(r) < expect["min_trades"]:
        return {"status": "collecting", "n": int(len(r))}
    se = r.std(ddof=1) / np.sqrt(len(r))
    z = (r.mean() - expect["avg_R"]) / se if se > 0 else 0.0
    win = float((r > 0).mean())
    status = "broken" if z < -2.5 else "weakening" if z < -1.5 else "healthy"
    return {"status": status, "n": int(len(r)), "avg_R": round(float(r.mean()), 3), "expected_avg_R": expect["avg_R"],
            "z_vs_backtest": round(float(z), 2), "win_rate": round(win, 3), "expected_win_rate": expect["win_rate"]}


def weekly_drift(st, D=None):
    reg = registry()
    rep = {"date": str(dt.date.today()), "signals": {}}
    need = {"SPY", *ASIA, "BTC-USD", "ETH-USD"}
    for s in reg["signals"].values():
        need |= set(s.get("targets", []))
    D = D or _closes(need, period="2y")
    for name, s in reg["signals"].items():
        if s["kind"] == "gap_nowcast":
            res = {}
            for t in s["targets"]:
                if t not in D:
                    continue
                gap = D[t].Open / D[t].Close.shift(1) - 1
                c, n = _rolling_corr(asia_composite(D, t), gap, s["window_days"])
                res[t] = {"corr": None if c is None else round(c, 3), "n": n}
            vals = [v["corr"] for v in res.values() if v["corr"] is not None]
            avg = float(np.mean(vals)) if vals else None
            floor = s["confirmation_corr"] * s["decay_floor"]
            status = ("collecting" if avg is None else "broken" if avg <= 0 else "weakening" if avg < floor else "healthy")
            rep["signals"][name] = {"status": status, "avg_corr": None if avg is None else round(avg, 3),
                                    "floor": round(floor, 3), "per_ticker": res}
        elif s["kind"] == "strategy":
            rep["signals"][name] = strategy_drift(st.get("book", {}).get("trades", []), s["expect"])
    st.setdefault("drift", []).append(rep)
    del st["drift"][:-26]
    return rep
