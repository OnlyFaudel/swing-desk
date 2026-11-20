import yfinance as yf, pandas as pd, numpy as np
from levels_lab import levels_signals, T
raw=yf.download(T,start="2012-01-01",auto_adjust=True,progress=False); D={t:raw.xs(t,axis=1,level=1).dropna() for t in T}
hr=yf.download(T,period="730d",interval="1h",auto_adjust=True,progress=False)
Hh={t:hr.xs(t,axis=1,level=1).dropna() for t in T}
for t in T: Hh[t].index=Hh[t].index.tz_convert("America/New_York")
for tgt in [0.01,0.015,0.02]:
  for stop_below in [0.02,0.01]:
    tr=[]
    for t in T:
        h=Hh[t]; start=h.index[0].date()
        sigs=[(d,L) for d,L in levels_signals(D[t]) if d.date()>start]
        busy=None
        for d,L in sigs:
            day=h[h.index.date==d.date()]
            if day.empty or (busy is not None and day.index[-1]<=busy): continue
            e=day.Close.iloc[-1]; stp=L*(1-stop_below); after=h[h.index>day.index[-1]].iloc[:7*5]
            res=None
            for ts,r in after.iterrows():
                if r.Low<=stp: res=(min(stp,r.Open)/e-1,ts,"stop");break
                if r.High>=e*(1+tgt): res=(max(tgt,r.Open/e-1),ts,"target");break
            if res is None and len(after): res=(after.Close.iloc[-1]/e-1,after.index[-1],"time")
            if res: busy=res[1]; tr.append((t,res[0]-0.001,res[2]))
    x=pd.DataFrame(tr,columns=["t","r","why"])
    print(f"HOURLY last 2y target +{tgt*100:.1f}% stop {stop_below*100:.0f}% below level: trades {len(x)} win {round((x.r>0).mean()*100)}% avg {x.r.mean()*100:.2f}% avg win {x.r[x.r>0].mean()*100:.2f}% avg loss {x.r[x.r<=0].mean()*100:.2f}% compounded(1/3 size) {(np.prod(1+x.r/3)-1)*100:.1f}%")
    print("   by stock:", {t:round(g.r.mean()*100,2) for t,g in x.groupby('t')})
