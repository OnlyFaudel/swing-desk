"""Shadow Desk: every Patient Levels setup on the wide universe, traded on paper with no money.
Once a day after the close: one batch download of 60 days of hourly bars, the same engine as the real trades,
and only trades that have fully closed are recorded (no peeking at open trades). ~4,000 practice trades a year.

learn_report(): patterns are only reported when they hold in BOTH the older and the newer half of the record."""
import datetime as dt
import numpy as np, pandas as pd
import patient

UNIVERSE = {
    "uranium/nuclear": ["CCJ", "NXE", "UEC", "DNN", "UUUU", "LEU", "BWXT", "SMR", "OKLO", "CEG", "VST", "TLN", "URNM"],
    "scarce materials": ["MP", "ALB", "FCX", "SCCO", "NEM", "AEM", "WPM", "SQM", "TECK"],
    "AI chips": ["NVDA", "AMD", "AVGO", "MU", "TSM", "ASML", "ARM", "MRVL", "SMCI", "SMH"],
    "AI power": ["ETN", "VRT", "GEV", "PWR", "NRG"],
    "high beta": ["PLTR", "TSLA", "COIN", "MSTR", "HOOD", "SOFI", "RKLB", "IONQ", "APP", "SHOP", "NOK"],
    "megacap": ["META", "AMZN", "MSFT", "GOOGL", "NFLX"],
}
GROUP = {t: g for g, ts in UNIVERSE.items() for t in ts}


def _bars(tickers, period="60d"):
    import yfinance as yf
    out = {}
    for i in range(0, len(tickers), 20):
        ch = tickers[i:i + 20]
        d = yf.download(ch, period=period, interval="1h", auto_adjust=True, progress=False, group_by="ticker", threads=True)
        for t in ch:
            try:
                h = d[t][["Open", "High", "Low", "Close"]].dropna().copy()
                h["Volume"] = 1.0
                h.index = h.index.tz_convert("America/New_York")
                if len(h) > 200:
                    out[t] = h
            except Exception:
                pass
    return out


def _group_up(bars):
    """Per group: was the equal-weight group basket above its 70-hour (~10 day) average? (series by timestamp)"""
    out = {}
    for g, ts in UNIVERSE.items():
        C = pd.DataFrame({t: bars[t].Close for t in ts if t in bars}).ffill().dropna(how="all")
        if C.empty:
            continue
        b = (C / C.bfill().iloc[0]).mean(axis=1)
        out[g] = (b > b.rolling(70).mean())
    return out


def _features(h, i, gup, grp):
    """What the market looked like just before the buy (only data known at that moment: bar i-1 and earlier)."""
    C = h.Close.values
    j = i - 1
    f = {"hour": int(h.index[i].hour)}
    if j >= 35:
        f["ret5d_pct"] = round(float((C[j] / C[j - 35] - 1) * 100), 2)
    if j >= 70:
        f["dist_avg_pct"] = round(float((C[j] / C[j - 69:j + 1].mean() - 1) * 100), 2)
    a = h.atr.values[j] if "atr" in h else np.nan
    if a == a:
        f["vol_pct"] = round(float(a / C[j] * 100), 3)
    s = gup.get(grp)
    if s is not None:
        v = s.asof(h.index[j]) if len(s) else None
        f["group_up"] = bool(v) if v is not None and v == v else None
    return f


def run_daily(st, bars=None, rebuild=False):
    """Record newly closed shadow trades (with the market context at entry). Returns a short summary for the feed."""
    sh = st.setdefault("shadow_desk", {"seen": {}, "trades": []})
    if rebuild:
        sh["seen"], sh["trades"] = {}, []
    first = not sh["seen"]
    bars = bars or _bars(list(GROUP), "729d" if rebuild else "60d")  # a rebuild replays ~2 years for the research lab
    gup = _group_up(bars)
    new = []
    for t, h in bars.items():
        last_bar = h.index[-1]
        seen = sh["seen"].get(t, "")
        hp = patient.prep(h)
        for f, x, ret, R in patient.simulate(hp, patient.LIVE):
            if abs(R) > 10:              # a bad print or split in the data, not a trade
                continue
            if x >= last_bar:            # still open (or closed by running out of data): not a result yet
                continue
            key = f.strftime("%Y-%m-%d %H:%M")
            if key <= seen:
                continue
            new.append({"tk": t, "group": GROUP.get(t, "?"), "entry": key, "exit": x.strftime("%Y-%m-%d %H:%M"),
                        "ret_pct": round(ret * 100, 3), "R": round(R, 3), "weekday": f.strftime("%a"),
                        "open_fill": f.hour == 9, **_features(hp, hp.index.get_loc(f), gup, GROUP.get(t))})
        done = [n["entry"] for n in new if n["tk"] == t]
        if done:
            sh["seen"][t] = max(done + [seen])
    sh["trades"].extend(new)
    del sh["trades"][:-20000]
    sh["last_run"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    if not new:
        return {"new": 0}
    R = np.array([n["R"] for n in new])
    best = max(new, key=lambda n: n["R"])
    return {"backfill": first, "new": len(new), "wins": int((R > 0).sum()), "sumR": round(float(R.sum()), 2),
            "best": f'{best["tk"]} {best["R"]:+.2f}R', "total": len(sh["trades"])}


def learn_report(st, min_n=30):
    """Which groupings beat the overall average in BOTH halves of the shadow record?"""
    tr = pd.DataFrame(st.get("shadow_desk", {}).get("trades", []))
    if len(tr) < 4 * min_n:
        return {"status": "collecting", "n": int(len(tr)), "patterns": []}
    tr = tr.sort_values("entry")
    half = tr.entry.iloc[len(tr) // 2]
    base = tr.R.mean()
    pats = []
    for col in ("group", "weekday", "open_fill", "tk"):
        for val, g in tr.groupby(col):
            a, b = g[g.entry < half], g[g.entry >= half]
            if len(a) < min_n or len(b) < min_n:
                continue
            da, db = a.R.mean() - tr[tr.entry < half].R.mean(), b.R.mean() - tr[tr.entry >= half].R.mean()
            if np.sign(da) == np.sign(db) and min(abs(da), abs(db)) > 0.1:
                pats.append({"what": f"{col} = {val}", "older_vs_avg_R": round(da, 2), "newer_vs_avg_R": round(db, 2),
                             "n": int(len(g)), "direction": "better" if da > 0 else "worse"})
    pats.sort(key=lambda p: -min(abs(p["older_vs_avg_R"]), abs(p["newer_vs_avg_R"])))
    return {"status": "ok", "n": int(len(tr)), "avg_R": round(float(base), 3), "patterns": pats[:8],
            "note": "Candidates only: a pattern found here still goes through the written-rule test before the bot uses it."}
