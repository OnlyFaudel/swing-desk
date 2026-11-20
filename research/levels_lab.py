"""Owner's strategy: buy when price tests a support level and holds, take a quick 1-2%.
Support = confirmed swing lows (lowest low of +/-5 days, confirmed 5 days later: no lookahead).
Test  = today's low dips to within 1% of a support level, and the day closes back above it.
Exit  = target hit (+1%, +1.5%, +2%, +3%), or stop 2% below the level, or 5 days."""
import yfinance as yf, pandas as pd, numpy as np, itertools, sys
T=["CCJ","MU","PLTR"]
def levels_signals(df,k=5,look=60,trend=None):
    lo=df.Low; piv=(lo==lo.rolling(2*k+1,center=True).min())
    sig=[]
    for i in range(look+2*k,len(df)):
        d=df.index[i]
        conf=[j for j in range(i-look,i-k) if piv.iloc[j]]           # confirmed by day i
        lv=[lo.iloc[j] for j in conf if lo.iloc[j] < df.Close.iloc[i-1]]
        if not lv: continue
        L=max(lv)                                                     # nearest support below
        r=df.iloc[i]
        if r.Low<=L*1.01 and r.Low>=L*0.97 and r.Close>L:
            if trend=="up" and not r.Close>df.Close.iloc[i-50:i].mean(): continue
            sig.append((d,L))
    return sig
def sim(D,start,end,tgt,trend=None,stop_below=0.02,maxhold=5):
    trades=[]
    for t in T:
        df=D[t]; s=[x for x in levels_signals(df,trend=trend) if start<=str(x[0].date())<=end]
        busy_until=None
        for d,L in s:
            if busy_until is not None and d<=busy_until: continue
            i=df.index.get_loc(d); e=df.Close.iloc[i]; stp=L*(1-stop_below); res=None
            for j in range(i+1,min(i+1+maxhold,len(df))):
                r=df.iloc[j]
                if r.Open<=stp: res=(r.Open/e-1,j,"stop");break
                if r.Low<=stp: res=(stp/e-1,j,"stop");break      # stop first if both (conservative)
                if r.Open>=e*(1+tgt): res=(r.Open/e-1,j,"target");break
                if r.High>=e*(1+tgt): res=(tgt,j,"target");break
            if res is None:
                j=min(i+maxhold,len(df)-1); res=(df.Close.iloc[j]/e-1,j,"time")
            busy_until=df.index[res[1]]; trades.append((t,d,res[0]-0.001,res[2],(df.index[res[1]]-d).days))
    tr=pd.DataFrame(trades,columns=["t","d","r","why","days"])
    if tr.empty: return {}
    return dict(trades=len(tr),per_yr=round(len(tr)/((pd.Timestamp(end)-pd.Timestamp(start)).days/365.25),1),
                win=round((tr.r>0).mean()*100),avg=round(tr.r.mean()*100,2),avg_win=round(tr.r[tr.r>0].mean()*100,2),
                avg_loss=round(tr.r[tr.r<=0].mean()*100,2),total_compound=round((np.prod(1+tr.r/3)-1)*100,1),
                stops=round((tr.why=="stop").mean()*100))
raw=yf.download(T,start="2012-01-01",auto_adjust=True,progress=False)
D={t:raw.xs(t,axis=1,level=1).dropna() for t in T}
print("DAILY BARS (conservative: if stop and target both touched same day, counts as stop)")
for (a,b) in [("2012-01-01","2020-12-31"),("2021-01-01","2026-12-31")]:
    for tgt,trend in itertools.product([0.01,0.015,0.02,0.03],[None,"up"]):
        print(f" {a[:4]}-{b[:4]} target +{tgt*100:.1f}% trend={trend or 'any'}:", sim(D,a,b,tgt,trend))
