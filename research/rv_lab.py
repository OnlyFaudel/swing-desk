"""Walk-forward relative-value trials on CCJ/TSM/ETN. Every variant is a trial for the Deflated Sharpe Ratio."""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, itertools, json
from scipy.stats import norm, skew, kurtosis
from statsmodels.tsa.vector_ar.vecm import coint_johansen
px=pd.read_pickle("rv_px.pkl"); T=list(px.columns); L=np.log(px); R=px.pct_change().fillna(0)
OOS="2019-01-01"; HALF="2023-01-01"; SIDE=0.001; BORROW=0.01/252   # 0.20% round trip = 0.10% per side
def run(W):  # W: target weights decided at close t (DataFrame), applied t+1
    W=W.reindex(R.index).ffill().fillna(0); w=W.shift(1).fillna(0)
    gross=(w*R).sum(axis=1); cost=W.diff().abs().sum(axis=1).shift(1).fillna(0)*SIDE; borrow=(-w.clip(upper=0)).sum(axis=1)*BORROW
    return (gross-cost-borrow).loc[OOS:]
def metrics(r):
    eq=(1+r).cumprod(); yrs=len(r)/252
    h1=(1+r[:HALF]).prod()**(252/len(r[:HALF]))-1; h2=(1+r[HALF:]).prod()**(252/len(r[HALF:]))-1
    return dict(ann=(eq.iloc[-1])**(1/yrs)-1, sharpe=r.mean()/r.std()*np.sqrt(252) if r.std()>0 else 0,
                mdd=(eq/eq.cummax()-1).min(), h1=h1, h2=h2, turnover=None)
trials={}
# ---------- A: trio Johansen spread, long-short (reference only)
def johansen_ls(win, entry, exit_=0.5, zlb=60, maxhold=60):
    W=pd.DataFrame(0.0,index=L.index,columns=T); pos=0; held=0; vec=None
    for i in range(win, len(L)):
        if (i-win)%21==0 or vec is None:   # re-estimate monthly on trailing window
            r=coint_johansen(L.iloc[i-win:i].values,0,1); vec=np.real(r.evec[:,0]); vec=vec/np.abs(vec).sum()
        sp=L.iloc[i-zlb:i+1].values@vec; z=(sp[-1]-sp[:-1].mean())/sp[:-1].std()
        if pos==0 and abs(z)>entry: pos=-np.sign(z); held=0
        elif pos!=0 and (abs(z)<exit_ or held>=maxhold or abs(z)>4): pos=0
        held+=1; W.iloc[i]=pos*vec
    return W
for win,entry in itertools.product([252,504],[1.5,2.0]):
    trials[f"A trio Johansen L/S win{win} entry{entry}"]=("ls",run(johansen_ls(win,entry)))
# ---------- B: pair ratio z-score, long-short (reference only)
def pair_ls(a,b,zlb,entry=2.0,exit_=0.5,win=252,maxhold=60):
    W=pd.DataFrame(0.0,index=L.index,columns=T); pos=0; held=0
    for i in range(win,len(L)):
        beta=np.polyfit(L[b].iloc[i-win:i],L[a].iloc[i-win:i],1)[0]
        sp=(L[a]-beta*L[b]).iloc[i-zlb:i+1].values; z=(sp[-1]-sp[:-1].mean())/sp[:-1].std()
        if pos==0 and abs(z)>entry: pos=-np.sign(z); held=0
        elif pos!=0 and (abs(z)<exit_ or held>=maxhold or abs(z)>4): pos=0
        held+=1; g=1+abs(beta); W.iloc[i,T.index(a)]=pos/g; W.iloc[i,T.index(b)]=-pos*beta/g
    return W
for (a,b),zlb in itertools.product(itertools.combinations(T,2),[20,60]):
    trials[f"B pair {a}/{b} L/S z{zlb}"]=("ls",run(pair_ls(a,b,zlb)))
# ---------- baseline: equal-weight trio, monthly rebalance (benchmark, not a trial)
EW=pd.DataFrame(np.nan,index=L.index,columns=T); EW[EW.index.is_month_start | (EW.index==EW.index[0])]=1/3
base=run(EW.ffill())
# ---------- C: long-only cheap-leg tilt (implementable)
def tilt(k,zlb):
    res=L.sub(L.mean(axis=1),axis=0)                      # each leg vs the basket (log)
    z=(res-res.rolling(zlb).mean())/res.rolling(zlb).std()
    raw=(1/3 - k/3*z.clip(-2,2)/2).clip(0,2/3); W=raw.div(raw.sum(axis=1),axis=0)
    return W[W.index.weekday==4].reindex(L.index)          # rebalance Fridays
for k,zlb in itertools.product([0.5,1.0],[20,60]):
    trials[f"C long-only cheap-leg tilt k{k} z{zlb}"]=("lo",run(tilt(k,zlb).ffill()))
# ---------- D: long-only laggard rotation (100% in the worst recent performer)
def rotate(lb):
    perf=px.pct_change(lb); W=pd.DataFrame(0.0,index=L.index,columns=T)
    for i in range(lb,len(L)): W.iloc[i,int(np.argmin(perf.iloc[i].values))]=1.0
    return W[W.index.weekday==4].reindex(L.index)
for lb in [5,20]:
    trials[f"D long-only laggard rotation {lb}d"]=("lo",run(rotate(lb).ffill()))
# ---------- DSR (Bailey & Lopez de Prado 2014) over ALL trials
judged={k:(r if kind=="ls" else r-base) for k,(kind,r) in trials.items()}
srs=np.array([r.mean()/r.std() for r in judged.values()]); N=len(srs); V=srs.var(ddof=1); g=0.5772156649
sr0=np.sqrt(V)*((1-g)*norm.ppf(1-1/N)+g*norm.ppf(1-1/(N*np.e)))
def dsr(r):
    sr=r.mean()/r.std(); n=len(r); sk=skew(r); ku=kurtosis(r,fisher=False)
    return norm.cdf((sr-sr0)*np.sqrt(n-1)/np.sqrt(1-sk*sr+(ku-1)/4*sr**2))
bm=metrics(base)
print(f"N trials = {N} | cross-trial Sharpe variance (daily) = {V:.2e} | SR* hurdle = {sr0*np.sqrt(252):.2f} annualized")
print(f"\nBENCHMARK equal-weight trio (OOS 2019-2026, net 0.2%): ann {bm['ann']*100:+.1f}% Sharpe {bm['sharpe']:.2f} maxDD {bm['mdd']*100:.0f}% halves {bm['h1']*100:+.1f}%/{bm['h2']*100:+.1f}%\n")
rows=[]
for k,(kind,r) in trials.items():
    m=metrics(r); a=judged[k]; d=dsr(a)
    lo=kind=="lo"
    passes={"DSR>=0.95":d>=0.95,"net>0 both halves":(m["h1"]>0 and m["h2"]>0) if not lo else ((1+a[:HALF]).prod()>1 and (1+a[HALF:]).prod()>1),
            "maxDD":(m["mdd"]>=-0.20) if not lo else (m["mdd"]>=bm["mdd"]),"implementable":lo}
    rows.append(dict(trial=k,ann=round(m["ann"]*100,1),sharpe=round(m["sharpe"],2),maxdd=round(m["mdd"]*100,0),
                     h1=round(m["h1"]*100,1),h2=round(m["h2"]*100,1),
                     active_ann=round(((1+a).prod()**(252/len(a))-1)*100,1) if lo else None,DSR=round(d,3),
                     PASS=all(passes.values()),failed=",".join(k2 for k2,v in passes.items() if not v)))
df=pd.DataFrame(rows); pd.set_option("display.width",250); pd.set_option("display.max_colwidth",44)
print(df.to_string(index=False))
df.to_csv("rv_results.csv",index=False)
# cost sensitivity for the best long-only trial and best L/S trial at 0.1%
json.dump({"N":N,"sr_star_ann":float(sr0*np.sqrt(252)),"benchmark":{k:float(v) for k,v in bm.items() if v is not None}},open("rv_summary.json","w"))
