"""CCJ correlation map: weekly raw / partial correlations + stability, discovery vs confirmation."""
import pickle, json, numpy as np, pandas as pd
from ccj_fetch import UNIV

D = pickle.load(open("ccj_univ.pkl", "rb"))
D.pop("KAP.L", None)
close = pd.DataFrame({t: d["Close"] for t, d in D.items()})
close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
close = close.sort_index()
# weekly Friday closes (last available print in each week, any exchange) -> removes time-zone overlap
wk = close.resample("W-FRI").last()
r = np.log(wk).diff()
r.loc[:, "^TNX"] = wk["^TNX"].diff() / 10  # yield change in points/10 (scale only)
r = r.iloc[1:]

def resid(y, X):
    m = pd.concat([y, X], axis=1).dropna()
    if len(m) < 30: return None
    A = np.c_[np.ones(len(m)), m.iloc[:, 1:].values]
    b = np.linalg.lstsq(A, m.iloc[:, 0].values, rcond=None)[0]
    return pd.Series(m.iloc[:, 0].values - A @ b, index=m.index)

def corr(a, b):
    m = pd.concat([a, b], axis=1).dropna()
    return (m.iloc[:, 0].corr(m.iloc[:, 1]), len(m)) if len(m) >= 30 else (np.nan, len(m))

rows = []
ccj = r["CCJ"]
ccj_s = resid(ccj, r[["SPY"]])
ccj_su = resid(ccj, r[["SPY", "URA"]])
for t in r.columns:
    if t == "CCJ": continue
    raw, n = corr(ccj, r[t])
    xs = resid(r[t], r[["SPY"]]) if t != "SPY" else None
    net_spy = corr(ccj_s, xs)[0] if xs is not None else np.nan
    xsu = resid(r[t], r[["SPY", "URA"]]) if t not in ("SPY", "URA") else None
    net_su = corr(ccj_su, xsu)[0] if xsu is not None else np.nan
    early = corr(ccj[:"2022-12-31"], r[t][:"2022-12-31"])[0]
    late = corr(ccj["2023-01-01":], r[t]["2023-01-01":])[0]
    # rolling 52w stability
    m = pd.concat([ccj, r[t]], axis=1).dropna()
    roll = m.iloc[:, 0].rolling(52).corr(m.iloc[:, 1]).dropna()
    rows.append(dict(ticker=t, name=UNIV[t], raw=raw, n=n, net_spy=net_spy, net_spy_ura=net_su,
                     early=early, late=late, roll_min=roll.min() if len(roll) else np.nan,
                     roll_max=roll.max() if len(roll) else np.nan,
                     roll_pct_above_03=(roll > 0.3).mean() if len(roll) else np.nan,
                     roll_last=roll.iloc[-1] if len(roll) else np.nan))
df = pd.DataFrame(rows).sort_values("raw", ascending=False)
pd.set_option("display.width", 250, "display.max_rows", 100)
print(df.round(2).to_string(index=False))
df.to_csv("ccj_corr_weekly.csv", index=False)

# beta of CCJ to drivers (weekly, full period) for the economic read
for t in ["U-UN.TO", "URA", "SPY", "QQQ", "CEG", "^TNX", "CAD=X", "CL=F", "BTC-USD"]:
    m = pd.concat([ccj, r[t]], axis=1).dropna()
    b = np.cov(m.iloc[:, 0], m.iloc[:, 1])[0, 1] / m.iloc[:, 1].var()
    print(f"beta CCJ~{t}: {b:.2f}")
