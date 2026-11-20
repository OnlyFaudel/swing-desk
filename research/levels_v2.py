"""Level strategy v2 ("get in front of the whales"):
- Zone = nearest confirmed swing-low support below price; stronger if it lines up with the 50/200-day
  average or a round number (confluence = where big resting orders tend to sit).
- Entry = resting LIMIT order slightly ABOVE the zone (front-run the bids), not after the close.
- Stop  = just below the zone. Target = the next resistance (prior swing high), only if reward >= 2x risk.
Tested on hourly bars (last 2 years) using daily levels known at the time (no lookahead)."""
import yfinance as yf, pandas as pd, numpy as np
T=["CCJ","MU","PLTR"]
raw=yf.download(T,start="2023-01-01",auto_adjust=True,progress=False); D={t:raw.xs(t,axis=1,level=1).dropna() for t in T}
hr=yf.download(T,period="730d",interval="1h",auto_adjust=True,progress=False)
H={t:hr.xs(t,axis=1,level=1).dropna() for t in T}
for t in T: H[t].index=H[t].index.tz_convert("America/New_York")
def piv(df,k=5):
    lo=df.Low==df.Low.rolling(2*k+1,center=True).min(); hi=df.High==df.High.rolling(2*k+1,center=True).max()
    return lo,hi
def run(front=0.004, stop_pad=0.012, min_rr=2.0, conf_req=False, trend=False, maxdays=10):
    trades=[]
    for t in T:
        df=D[t]; lo,hi=piv(df); h=H[t]; s50=df.Close.rolling(50).mean(); s200=df.Close.rolling(200).mean()
        days=[d for d in df.index if d.date()>=h.index[0].date()]
        pos=None; busy=None
        for d in days:
            i=df.index.get_loc(d)
            if i<70 or (busy is not None and d<=busy): continue
            prev=df.Close.iloc[i-1]
            sup=[df.Low.iloc[j] for j in range(i-60,i-5) if lo.iloc[j] and df.Low.iloc[j]<prev*0.995]
            res=[df.High.iloc[j] for j in range(i-120,i-5) if hi.iloc[j] and df.High.iloc[j]>prev*1.01]
            if not sup or not res: continue
            Z=max(sup); R=min(res)
            near_ma=any(abs(Z/m-1)<0.015 for m in (s50.iloc[i-1],s200.iloc[i-1]) if not np.isnan(m))
            mag=10**int(np.log10(Z)); rnd=min(abs(Z-x) for x in np.arange(0,Z*2,mag/2 if mag>=10 else 1))/Z<0.01
            if conf_req and not (near_ma or rnd): continue
            if trend and not prev>s50.iloc[i-1]: continue
            entry=Z*(1+front); stop=Z*(1-stop_pad); risk=entry-stop
            if (R-entry)<min_rr*risk or entry>=prev: continue
            day=h[h.index.date==d.date()]
            if day.empty: continue
            hit=day[day.Low<=entry]
            if hit.empty: continue
            ts0=hit.index[0]; e=min(entry,hit.Open.iloc[0])
            after=h[h.index>=ts0]; out=None
            for ts,r in after.iloc[:7*maxdays].iterrows():
                if r.Low<=stop: out=(min(stop,r.Open)/e-1,ts,"stop");break
                if r.High>=R: out=(max(R,r.Open)/e-1 if ts!=ts0 else R/e-1,ts,"target");break
            if out is None: out=(after.Close.iloc[min(len(after),7*maxdays)-1]/e-1,after.index[min(len(after),7*maxdays)-1],"time")
            busy=pd.Timestamp(out[1].date()); trades.append((t,out[0]-0.001,out[2]))
    x=pd.DataFrame(trades,columns=["t","r","why"])
    if x.empty: return "no trades"
    return (f"trades {len(x)} win {round((x.r>0).mean()*100)}% avg {x.r.mean()*100:+.2f}% win {x.r[x.r>0].mean()*100:+.2f}% "
            f"loss {x.r[x.r<=0].mean()*100:+.2f}% comp(1/3) {(np.prod(1+x.r/3)-1)*100:+.1f}% | by stock "
            + str({k:round(g.r.mean()*100,2) for k,g in x.groupby('t')}))
for kw in [dict(),dict(min_rr=1.5),dict(conf_req=True),dict(trend=True),dict(conf_req=True,trend=True),dict(front=0.0),dict(front=0.008),dict(stop_pad=0.02)]:
    print(kw or "default", "->", run(**kw))
