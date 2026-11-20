import warnings; warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd, numpy as np, itertools, json
from statsmodels.tsa.stattools import coint, adfuller
from statsmodels.tsa.vector_ar.vecm import coint_johansen
T=["CCJ","TSM","ETN"]
px=yf.download(T,start="2015-01-01",auto_adjust=True,progress=False)["Close"].dropna()
px.to_pickle("rv_px.pkl"); L=np.log(px)
def half_life(s):
    s=s.dropna(); d=s.diff().dropna(); lag=s.shift().dropna().loc[d.index]
    b=np.polyfit(lag.values,d.values,1)[0]; return -np.log(2)/b if b<0 else np.inf
def johansen(df):
    r=coint_johansen(df.values,0,1); return r.lr1[0]>r.cvt[0,1], r.evec[:,0]   # trace r=0 rejected at 5%?
print(f"Data {px.index[0].date()} -> {px.index[-1].date()}, {len(px)} days")
print("\nFULL SAMPLE")
for a,b in itertools.combinations(T,2):
    t,p,_=coint(L[a],L[b]); beta=np.polyfit(L[b],L[a],1)[0]; sp=L[a]-beta*L[b]
    print(f"  Engle-Granger {a}~{b}: p={p:.3f}  half-life {half_life(sp):.0f}d")
ok,v=johansen(L); sp=L.values@v
print(f"  Johansen trio trace test rejects 'no cointegration' at 5%: {ok}; half-life {half_life(pd.Series(sp,index=L.index)):.0f}d")
print("\nROLLING 2-YEAR WINDOWS (step 1 quarter)")
res={k:[] for k in ["CCJ~TSM","CCJ~ETN","TSM~ETN","trio"]}; hl=[]
for end in pd.date_range("2017-01-01",px.index[-1],freq="QS"):
    w=L.loc[end-pd.DateOffset(years=2):end]
    if len(w)<400: continue
    for a,b in itertools.combinations(T,2): res[f"{a}~{b}"].append(coint(w[a],w[b])[1]<0.05)
    ok,v=johansen(w); res["trio"].append(bool(ok)); hl.append(half_life(pd.Series(w.values@v,index=w.index)))
for k,v in res.items(): print(f"  {k:8s} cointegrated in {100*np.mean(v):.0f}% of {len(v)} windows")
hl=np.array(hl); print(f"  trio spread half-life across windows: median {np.median(hl[np.isfinite(hl)]):.0f}d, range {np.nanmin(hl):.0f}-{np.nanmax(hl[np.isfinite(hl)]):.0f}d")
json.dump({k:float(np.mean(v)) for k,v in res.items()},open("rv_coint.json","w"))
