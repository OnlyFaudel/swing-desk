import warnings, sys, json, pickle; warnings.filterwarnings("ignore"); sys.path.insert(0,"..")
import numpy as np, pandas as pd, patient
from scipy.stats import norm, skew, kurtosis
lab=json.load(open("../docs/lab.json")); T=["CCJ","TSM","ETN"]
def bars(t):
    b=lab[t]; return patient.prep(pd.DataFrame({"Open":b["o"],"High":b["h"],"Low":b["l"],"Close":b["c"],"Volume":1.0},
        index=pd.to_datetime(b["t"],unit="s",utc=True).tz_convert("America/New_York")))
H={t:bars(t) for t in T}; DL={t:patient.daily_levels(pickle.load(open("bars.pkl","rb"))["d"][t]) for t in T}
mid=H["CCJ"].index[len(H["CCJ"])//2]
base={"through_pct":0.1,"cost_rt":0.2}
V={"1d order":{"valid":7},"2d":{"valid":14},"3d":{"valid":21},"4d":{"valid":28},"5d (LIVE)":{"valid":35},"7d":{"valid":49},
   "2+touches":{"min_touches":2},"daily confl":{"daily_confluence":True},"ATR1":{"stop_mode":"atr","atr_mult":1.0},"ATR1.5":{"stop_mode":"atr","atr_mult":1.5},
   "BE1R":{"be_at_R":1.0},"half@1R":{"partial_at_R":1.0},"half@1.5R":{"partial_at_R":1.5},"trail1R":{"trail_R":1.0},"trail2R":{"trail_R":2.0},
   "skip930":{"skip_first_bar":True},"hold5d":{"maxh":35},"rr1.2":{"rr":1.2},"rr2":{"rr":2.0},"rr3":{"rr":3.0},"k3":{"k":3},"k8":{"k":8},
   "2d+skip":{"valid":14,"skip_first_bar":True},"2d+hold5":{"valid":14,"maxh":35},"2d+ATR1":{"valid":14,"stop_mode":"atr","atr_mult":1.0},
   "2d+BE":{"valid":14,"be_at_R":1.0},"2d+skip+hold5":{"valid":14,"skip_first_bar":True,"maxh":35},"3d+skip":{"valid":21,"skip_first_bar":True},
   "pad2":{"pad":2.0},"front0":{"front":0.0}}
days=pd.bdate_range(H["CCJ"].index[0].date(),H["CCJ"].index[-1].date())
def daily_returns(p):
    ev=sorted([(x[0],x[1],x[2],t) for t in T for x in patient.simulate(H[t],{**base,**p},DL[t])])
    eq=1000.0; open_=[]; pnl=pd.Series(0.0,index=days)
    for en,ex,ret,t in ev:
        open_=[o for o in open_ if o[1]>en] 
        if len(open_)>=3 or any(o[3]==t for o in open_): continue
        size=eq/3; open_.append((en,ex,ret,t)); d=pd.Timestamp(ex.date())
        if d in pnl.index: pnl[d]+=size*ret
        eq+=size*ret
    eqs=1000+pnl.cumsum(); return (eqs/eqs.shift().fillna(1000)-1)
R={k:daily_returns(p) for k,p in V.items()}
test={k:r[r.index>=mid.tz_localize(None)] for k,r in R.items()}
srs=np.array([r.mean()/r.std() for r in test.values()]); N=len(srs); Vs=srs.var(ddof=1); g=0.5772156649
sr0=np.sqrt(Vs)*((1-g)*norm.ppf(1-1/N)+g*norm.ppf(1-1/(N*np.e)))
def dsr(r):
    sr=r.mean()/r.std(); return norm.cdf((sr-sr0)*np.sqrt(len(r)-1)/np.sqrt(1-skew(r)*sr+(kurtosis(r,fisher=False)-1)/4*sr**2))
print(f"N={N} trials | SR* hurdle (test half) {sr0*np.sqrt(252):.2f} annualized")
for k in ["5d (LIVE)","7d","1d order","rr2"]:
    r=R[k]; t1=r[r.index<mid.tz_localize(None)]; t2=test[k]; eq=(1+r).cumprod()
    a=lambda x:((1+x).prod()**(252/len(x))-1)*100
    print(f"{k:10s} tune {a(t1):+.0f}%/yr  test {a(t2):+.0f}%/yr  test Sharpe {t2.mean()/t2.std()*np.sqrt(252):.2f}  maxDD {((eq/eq.cummax())-1).min()*100:.0f}%  DSR(test) {dsr(t2):.3f}")
