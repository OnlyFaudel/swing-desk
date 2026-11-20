"""Does the pre-open Asia nowcast change the outcome of Patient Levels trades? (overlay test, not a new strategy)"""
import json, sys, pickle, numpy as np, pandas as pd
sys.path.insert(0, ".."); import patient
from scipy import stats as st

lab = json.load(open("../docs/lab.json"))
D = pickle.load(open("ccj_univ.pkl", "rb"))
for t in D: D[t].index = pd.to_datetime(D[t].index).tz_localize(None).normalize()
us = D["CCJ"].index
spy_prev = D["SPY"].Close.pct_change().reindex(us).shift(1)

def asia_resid(t, own):
    a = D[t].Close.pct_change().reindex(us)
    X = pd.concat([a, spy_prev, own], axis=1).dropna()
    A = np.c_[np.ones(len(X)), X.iloc[:, 1:]]
    b = np.linalg.lstsq(A, X.iloc[:, 0], rcond=None)[0]
    e = (X.iloc[:, 0] - A @ b); return (e / e.std()).reindex(us)

rows = []
for tk in ["CCJ", "TSM", "ETN"]:
    L = lab[tk]
    h = pd.DataFrame({"Open": L["o"], "High": L["h"], "Low": L["l"], "Close": L["c"], "Volume": 1.0},
                     index=pd.to_datetime(L["t"], unit="s", utc=True).tz_convert("America/New_York"))
    tr = patient.simulate(patient.prep(h), patient.LIVE)
    own = D[tk].Close.pct_change().reindex(us).shift(1)
    comp = pd.concat([asia_resid(t, own) for t in ["^N225", "^KS11", "^HSI", "^AXJO"]], axis=1).mean(axis=1)
    gapx = (D[tk].Open / D[tk].Close.shift(1) - 1).reindex(us)
    for f, x, ret, R in tr:
        d = pd.Timestamp(f.date())
        rows.append(dict(tk=tk, fill=f, ret=ret, R=R, open_fill=f.hour == 9, asia=comp.get(d, np.nan), gap=gapx.get(d, np.nan)))
df = pd.DataFrame(rows).dropna()
print("trades", len(df), "avg %", round(df.ret.mean() * 100, 3))
print(df.groupby("open_fill").ret.agg(["count", "mean"]).assign(mean=lambda z: z["mean"] * 100).round(3))
df["asia_bucket"] = pd.cut(df.asia, [-9, -0.75, 0.75, 9], labels=["asia_down", "flat", "asia_up"])
print(df.groupby("asia_bucket", observed=True).ret.agg(["count", "mean"]).assign(mean=lambda z: z["mean"] * 100).round(3))
r = st.spearmanr(df.asia, df.ret); print("spearman asia vs trade ret", round(r.statistic, 3), round(r.pvalue, 3))
of = df[df.open_fill]
r2 = st.spearmanr(of.gap, of.ret); print("open fills: spearman gap vs ret", round(r2.statistic, 3), round(r2.pvalue, 3), len(of))
for half, sub in (("first half", df[df.fill < df.fill.median()]), ("second half", df[df.fill >= df.fill.median()])):
    print(half, sub.groupby("asia_bucket", observed=True).ret.mean().mul(100).round(3).to_dict())
df.to_csv("ccj_overlay_trades.csv", index=False)
