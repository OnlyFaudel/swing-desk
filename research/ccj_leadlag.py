"""Market-hours lead-lag for CCJ. Discovery 2019-2022 (BH-FDR q=0.10), confirmation 2023-2026.

Signals are only things known BEFORE the CCJ trade is placed:
  A  Asia/Australia close (date t) — residualised on the prior US session — vs CCJ gap(t) and open->close(t)
  B  Crypto weekend move (Fri 19:00 ET -> Sun 19:00 ET) vs Monday gap and open->close
  C  Prior US session (t-1) returns vs CCJ open->close(t) [all]; close->close(t) for assets that close <=16:00 ET
  D  CCJ residual vs physical uranium / miners (5-day z) vs next 1d and next 5d CCJ
"""
import pickle, json, numpy as np, pandas as pd, statsmodels.api as sm

D = pickle.load(open("ccj_univ.pkl", "rb")); D.pop("KAP.L", None)
for t in D:
    D[t].index = pd.to_datetime(D[t].index).tz_localize(None).normalize()
ccj = D["CCJ"]; us = ccj.index
gap = (ccj.Open / ccj.Close.shift(1) - 1)
oc = (ccj.Close / ccj.Open - 1)
cc = ccj.Close.pct_change()
cc5 = ccj.Close.shift(-5) / ccj.Close - 1  # forward 5d from close t

def ret_own(t):  # close-to-close on the asset's own calendar
    c = D[t].Close.dropna(); return c.pct_change()

spy_prev = ret_own("SPY").reindex(us).shift(1)
ccj_prev = cc.shift(1)

ASIA = ["^N225", "^KS11", "^HSI", "^AXJO", "9501.T", "9503.T", "7011.T", "034020.KS", "1816.HK", "PDN.AX", "BOE.AX"]
US_EQ = ["CCJ", "CCO.TO", "U-UN.TO", "URNM", "URA", "DNN", "NXE", "UEC", "LEU", "BWXT", "CEG", "VST", "OKLO", "SMR",
         "SPY", "QQQ", "SMH", "NVDA", "ETN", "XLU", "^TNX", "YCA.L"]
LATE = ["CL=F", "NG=F", "HG=F", "GC=F", "BTC-USD", "ETH-USD", "CAD=X", "KZT=X", "JPY=X"]

tests = []  # (family, signal_name, series, target_name, target_series, hac_lags)
for t in ASIA:
    a = ret_own(t).reindex(us)
    X = pd.concat([a, spy_prev, ccj_prev], axis=1).dropna()
    b = np.linalg.lstsq(np.c_[np.ones(len(X)), X.iloc[:, 1:]], X.iloc[:, 0], rcond=None)[0]
    res = (X.iloc[:, 0] - np.c_[np.ones(len(X)), X.iloc[:, 1:]] @ b).reindex(us)
    for tn, ts in (("gap", gap), ("open_to_close", oc)):
        tests.append(("A_asia_close", t, res, tn, ts, 1))

# B weekend crypto: Monday (or first session after a weekend) only
for t in ["BTC-USD", "ETH-USD"]:
    c = D[t].Close
    sig = {}
    for d in us:
        prev_us = us[us < d]
        if len(prev_us) == 0 or (d - prev_us[-1]).days < 3: continue
        p = prev_us[-1]                     # last US session (e.g. Friday)
        d_before = d - pd.Timedelta(days=1)  # bar ending 19:00 ET the evening before the open
        if p in c.index and d_before in c.index:
            sig[d] = c[d_before] / c[p] - 1
    s = pd.Series(sig).reindex(us)
    for tn, ts in (("gap", gap), ("open_to_close", oc)):
        tests.append(("B_crypto_weekend", t, s, tn, ts, 1))

for t in US_EQ:
    s = (cc if t == "CCJ" else ret_own(t).reindex(us)).shift(1)
    tests.append(("C_prior_session", t, s, "open_to_close", oc, 1))
    if t != "YCA.L":
        tests.append(("C_prior_session", t, s, "close_to_close", cc, 1))
for t in LATE:
    s = ret_own(t).reindex(us).shift(1)
    tests.append(("C_prior_session", t, s, "open_to_close", oc, 1))

# D CCJ residual vs physical uranium and miners
for t in ["U-UN.TO", "URNM"]:
    x = np.log(D[t].Close.reindex(us)).diff(); y = np.log(ccj.Close).diff()
    beta = (y.rolling(120).cov(x) / x.rolling(120).var()).shift(1)
    e = (y - beta * x)
    z = e.rolling(5).sum() / (e.rolling(60).std() * np.sqrt(5))
    tests.append(("D_resid_reversion", t, z, "next_close_to_close", cc.shift(-1), 1))
    tests.append(("D_resid_reversion", t, z, "next_5d", cc5, 5))

def fit(s, y, lags, lo, hi):
    m = pd.concat([s, y], axis=1).loc[lo:hi].dropna()
    if len(m) < 100: return np.nan, np.nan, len(m), np.nan
    xs = (m.iloc[:, 0] - m.iloc[:, 0].mean()) / m.iloc[:, 0].std()
    r = sm.OLS(m.iloc[:, 1].values, sm.add_constant(xs.values)).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return r.params[1], r.pvalues[1], len(m), np.corrcoef(xs, m.iloc[:, 1])[0, 1]

rows = []
for fam, sn, s, tn, ts, lags in tests:
    b1, p1, n1, c1 = fit(s, ts, lags, "2019-01-01", "2022-12-31")
    b2, p2, n2, c2 = fit(s, ts, lags, "2023-01-01", "2026-12-31")
    rows.append(dict(family=fam, signal=sn, target=tn, disc_bps_per_sd=b1 * 1e4, disc_p=p1, disc_n=n1, disc_corr=c1,
                     conf_bps_per_sd=b2 * 1e4, conf_p=p2, conf_n=n2, conf_corr=c2))
df = pd.DataFrame(rows)
# BH on discovery
ok = df.disc_p.notna()
p = df.loc[ok, "disc_p"].values; order = np.argsort(p); m = len(p)
thr = np.zeros(m, bool)
passed = p[order] <= (np.arange(1, m + 1) / m) * 0.10
k = np.where(passed)[0].max() + 1 if passed.any() else 0
thr[order[:k]] = True
df.loc[ok, "bh_disc"] = thr
df["confirmed"] = df.bh_disc.fillna(False) & (np.sign(df.disc_bps_per_sd) == np.sign(df.conf_bps_per_sd)) & (df.conf_p < 0.05)
pd.set_option("display.width", 250, "display.max_rows", 200)
print("tests:", len(df))
print(df.sort_values("disc_p").round(3).to_string(index=False))
df.to_csv("ccj_leadlag.csv", index=False)
