"""Hourly support-level engine with optional upgrades. Same logic is ported to the browser (Level Lab).
Bars: DataFrame with Open High Low Close Volume, hourly, ET index. Costs: cost_rt round trip per trade."""
import numpy as np, pandas as pd

DEFAULT = dict(k=5, look=70, front=0.4, stop_mode="pct", pad=1.2, atr_mult=1.0, rr=1.5, maxh=21, valid=7,
               min_touches=1, daily_confluence=False, vol_mult=0.0, be_at_R=0.0, partial_at_R=0.0, trail_R=0.0,
               skip_first_bar=False, spy_filter=False, cancel_below_zone=False, through_pct=0.0, cost_rt=0.1)

def prep(h):
    h = h.copy()
    k = 5
    h["plo"] = h.Low == h.Low.rolling(2*k+1, center=True).min()
    h["phi"] = h.High == h.High.rolling(2*k+1, center=True).max()
    pc = h.Close.shift()
    tr = pd.concat([h.High-h.Low, (h.High-pc).abs(), (h.Low-pc).abs()], axis=1).max(axis=1)
    h["atr"] = tr.rolling(14).mean()
    h["vavg"] = h.Volume.rolling(70).mean()
    return h

def daily_levels(d, k=5):
    lo = d.Low == d.Low.rolling(2*k+1, center=True).min()
    out = []
    for i in range(len(d)):
        if lo.iloc[i]:
            out.append((d.index[i] + pd.Timedelta(days=k+1), float(d.Low.iloc[i])))  # usable k+1 days later
    s50 = d.Close.rolling(50).mean(); s200 = d.Close.rolling(200).mean()
    return out, s50, s200

def simulate(h, p=None, daily=None, spy_ok=None):
    P = dict(DEFAULT); P.update(p or {})
    k, look = P["k"], P["look"]
    O, H, L, C, V = (h[c].values for c in ("Open","High","Low","Close","Volume"))
    plo, phi, atr, vavg = h.plo.values, h.phi.values, h.atr.values, h.vavg.values
    idx = h.index; n = len(h); trades = []
    dl = daily[0] if daily else None
    i = look*2 + k
    while i < n-1:
        prev = C[i-1]
        sup_j = [j for j in range(i-look, i-k) if plo[j] and L[j] < prev*0.995]
        res = [H[j] for j in range(i-look*2, i-k) if phi[j] and H[j] > prev*1.01]
        if not sup_j or not res: i += 1; continue
        jz = max(sup_j, key=lambda j: L[j]); Z = L[jz]; R = min(res)
        # --- upgrades: level quality filters
        if P["min_touches"] > 1:
            touches = sum(1 for j in range(i-look*2, i-k) if plo[j] and abs(L[j]/Z-1) < 0.005)
            if touches < P["min_touches"]: i += 1; continue
        if P["vol_mult"] > 0 and not (V[jz] > P["vol_mult"]*(vavg[jz] if vavg[jz] == vavg[jz] else 0)): i += 1; continue
        if P["daily_confluence"] and daily:
            t0 = idx[i]
            dz = [lv for (ts, lv) in dl if ts <= t0.tz_localize(None) and abs(lv/Z-1) < 0.015]
            s50 = daily[1][:t0.tz_localize(None)]; s200 = daily[2][:t0.tz_localize(None)]
            mas = [x.iloc[-1] for x in (s50, s200) if len(x) and x.iloc[-1] == x.iloc[-1]]
            if not dz and not any(abs(m/Z-1) < 0.015 for m in mas): i += 1; continue
        if P["spy_filter"] and spy_ok is not None and not spy_ok.get(idx[i].date(), True): i += 1; continue
        e = Z*(1+P["front"]/100)
        s = Z*(1-P["pad"]/100) if P["stop_mode"] == "pct" else e - P["atr_mult"]*atr[i-1]
        if not (s < e) or R-e < P["rr"]*(e-s) or e >= prev: i += 1; continue
        f = None
        for j in range(i, min(i+P["valid"], n)):
            if P["skip_first_bar"] and idx[j].hour == 9: continue
            if L[j] <= e*(1-P["through_pct"]/100): f = j; break
            if P["cancel_below_zone"] and C[j] < Z: break
        if f is None: i += 1; continue
        ep = min(e, O[f]); risk = ep - s; stop = s; got = 0.0; w = 1.0; out = None
        for j in range(f, min(f+P["maxh"], n)):
            if L[j] <= stop: out = (min(stop, O[j] if j > f else ep), j); break  # gap through stop: out at fill
            hi = H[j]
            if P["partial_at_R"] and w == 1.0 and hi >= ep + P["partial_at_R"]*risk and j > f:
                got += 0.5*(P["partial_at_R"]*risk/ep); w = 0.5; stop = max(stop, ep)
            if P["be_at_R"] and hi >= ep + P["be_at_R"]*risk and j > f: stop = max(stop, ep)
            if P["trail_R"] and j > f: stop = max(stop, hi - P["trail_R"]*risk) if hi >= ep + P["trail_R"]*risk else stop
            if hi >= R and j > f: out = (max(R, O[j]), j); break
        if out is None: j = min(f+P["maxh"], n-1); out = (C[j], j)
        ret = got + w*(out[0]/ep - 1) - P["cost_rt"]/100
        trades.append((idx[f], idx[out[1]], ret, ret/(risk/ep)))
        i = out[1] + 1
    return trades

def stats(trs):
    r = np.array([t[2] for t in trs]) if trs else np.array([])
    if len(r) < 2: return dict(n=len(r), avg=np.nan, t=np.nan, win=np.nan, sum=np.nan)
    return dict(n=len(r), avg=round(r.mean()*100, 3), t=round(r.mean()/r.std()*np.sqrt(len(r)), 2),
                win=round((r > 0).mean()*100), sum=round(r.sum()*100, 1))


# ======================================================================= live use
LIVE = dict(DEFAULT, valid=35, through_pct=0.0)   # Patient Levels: order rests up to 5 sessions


def setup_now(h, p=None):
    """The setup the bot would arm right now from hourly bars h (index = last completed bars). None if no clean level."""
    P = dict(LIVE); P.update(p or {})
    if h is None or len(h) < P["look"] * 2 + P["k"] + 2:
        return None
    h = prep(h) if "plo" not in h else h
    k, look = P["k"], P["look"]
    n = len(h)
    L, Hh, C = h.Low.values, h.High.values, h.Close.values
    plo, phi = h.plo.values, h.phi.values
    prev = C[-1]
    sup = [L[j] for j in range(n - look, n - k) if plo[j] and L[j] < prev * 0.995]
    res = [Hh[j] for j in range(n - look * 2, n - k) if phi[j] and Hh[j] > prev * 1.01]
    if not sup or not res:
        return None
    Z, R = max(sup), min(res)
    e = Z * (1 + P["front"] / 100)
    s = Z * (1 - P["pad"] / 100)
    if e >= prev or R - e < P["rr"] * (e - s):
        return None
    return {"setup": "patient_level", "zone": round(float(Z), 2), "entry": round(float(e), 2), "stop": round(float(s), 2),
            "target": round(float(R), 2), "reward_risk": round(float((R - e) / (e - s)), 2),
            "dist_to_entry_pct": round(float((prev / e - 1) * 100), 2), "max_days": 3, "valid_sessions": 5}


def rank_universe(hourly, weeks=26, prior=0.2, k=10, p=None):
    """Weekly self-selection: trailing `weeks` of the rule's own results per ticker, shrunk toward `prior` (% per trade)
    with the weight of k trades so a few lucky trades can't win the ranking."""
    out = {}
    for t, h in hourly.items():
        if h is None or len(h) < 400:
            continue
        xs = simulate(prep(h), dict(LIVE, **(p or {})))
        cut = h.index[-1] - pd.Timedelta(weeks=weeks)
        r = [x[2] * 100 for x in xs if x[1] >= cut]
        out[t] = {"trades": len(r), "avg_pct": round(float(np.mean(r)), 3) if r else None,
                  "score": round((prior * k + sum(r)) / (k + len(r)), 3)}
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["score"]))


def why_no_setup(h, p=None):
    """Plain-English reason setup_now() found nothing (for the 'What's happening' page)."""
    P = dict(LIVE); P.update(p or {})
    if h is None or len(h) < P["look"] * 2 + P["k"] + 2:
        return "not enough recent price history yet"
    h = prep(h) if "plo" not in h else h
    k, look, n = P["k"], P["look"], len(h)
    L, Hh, C = h.Low.values, h.High.values, h.Close.values
    prev = C[-1]
    sup = [L[j] for j in range(n - look, n - k) if h.plo.values[j] and L[j] < prev * 0.995]
    res = [Hh[j] for j in range(n - look * 2, n - k) if h.phi.values[j] and Hh[j] > prev * 1.01]
    if not sup:
        return "no confirmed support level below the price (it has been falling through them)"
    if not res:
        return "no resistance level above to aim for"
    Z, R = max(sup), min(res)
    e, s = Z * (1 + P["front"] / 100), Z * (1 - P["pad"] / 100)
    if e >= prev:
        return "the price is already sitting on its support"
    return f"the next resistance (${R:.2f}) is too close to make the trade worth its risk"
