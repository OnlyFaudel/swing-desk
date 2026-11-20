"""Short-term setups on CCJ/MU/PLTR. Costs: 0.05% per side (0.10% round trip). Long only."""
import yfinance as yf, pandas as pd, numpy as np
T=["CCJ","MU","PLTR"]; RT=0.001
H=yf.download(T,period="730d",interval="1h",auto_adjust=True,progress=False,prepost=False)
D=yf.download(T,period="3y",auto_adjust=True,progress=False)
M=yf.download(T,period="60d",interval="5m",auto_adjust=True,progress=False)
def g(df,t):
    x=df.xs(t,axis=1,level=1).dropna()
    if x.index.tz is not None: x.index=x.index.tz_convert("America/New_York")
    return x
def summ(name,rets):
    r=pd.Series(rets,dtype=float)
    if r.empty: print(f"{name:42s} no trades"); return
    t=r.groupby(level=0).apply(list) if False else None
    print(f"{name:42s} n={len(r):4d} win={100*(r>0).mean():4.0f}% avg={100*r.mean():+.3f}% med={100*r.median():+.2f}% "
          f"avgW={100*r[r>0].mean():+.2f}% avgL={100*r[r<=0].mean():+.2f}% sum={100*r.sum():+.1f}% t={r.mean()/r.std()*np.sqrt(len(r)):.2f}")
rows={}
for t in T:
    h=g(H,t); d=g(D,t); m=g(M,t)
    h["date"]=h.index.date; days=sorted(set(h["date"]))
    dc=d.Close; dc.index=dc.index.date; sma50=d.Close.rolling(50).mean(); sma50.index=sma50.index.date
    for day in days[1:]:
        x=h[h.date==day]
        if len(x)<6: continue
        prev=[k for k in dc.index if k<day]
        if not prev: continue
        pc=dc[prev[-1]]; up=bool(pc>sma50.get(prev[-1],np.nan))
        o=x.Open.iloc[0]; c=x.Close.iloc[-1]; fh_hi,fh_lo,fh_c=x.High.iloc[0],x.Low.iloc[0],x.Close.iloc[0]
        rest=x.iloc[1:]
        # 1) first-hour range breakout (long): buy break of first-hour high, stop first-hour low, exit close
        b=rest[rest.High>fh_hi]
        if len(b):
            i=rest.index.get_loc(b.index[0]); e=max(fh_hi,b.Open.iloc[0]); ex=c
            for _,r in rest.iloc[i:].iterrows():
                if r.Low<=fh_lo: ex=fh_lo; break
            rows.setdefault("1h ORB long (all days)",[]).append(ex/e-1-RT)
            if up: rows.setdefault("1h ORB long (only in uptrend)",[]).append(ex/e-1-RT)
        # 2) intraday momentum: prev close -> end of first hour > +1% => buy last half-hour bar open, sell close
        fhr=fh_c/pc-1
        lastbar=x.iloc[-1]
        if fhr>0.01: rows.setdefault("First-hour up >1% -> buy last 30 min",[]).append(lastbar.Close/lastbar.Open-1-RT)
        if fhr>0.01: rows.setdefault("First-hour up >1% -> hold 10:30 to close",[]).append(c/fh_c-1-RT)
        # 3) gaps
        gap=o/pc-1
        if gap<-0.02:
            ex=c; tgt=pc; stp=o*0.97
            for _,r in x.iterrows():
                if r.Low<=stp: ex=stp; break
                if r.High>=tgt: ex=tgt; break
            rows.setdefault("Gap down >2%: buy open, target fill, stop -3%",[]).append(ex/o-1-RT)
            if up: rows.setdefault("  ...gap down in uptrend only",[]).append(ex/o-1-RT)
        if gap>0.02 and fh_c>o: rows.setdefault("Gap up >2% + green first hour -> to close",[]).append(c/fh_c-1-RT)
        # 4) overnight: buy prev close, sell today open
        rows.setdefault("Overnight hold (close -> next open)",[]).append(o/pc-1-RT)
        rows.setdefault("Intraday hold (open -> close), reference",[]).append(c/o-1-RT)
    # 5) 5-min ORB (Zarattini-style long-only) on last 60 days
    m["date"]=m.index.date
    for day in sorted(set(m.date)):
        x=m[m.date==day]
        if len(x)<20: continue
        f=x.iloc[0]
        if f.Close<=f.Open: continue
        e=x.Open.iloc[1]; stp=f.Low; R=e-stp; ex=x.Close.iloc[-1]
        if R<=0: continue
        for _,r in x.iloc[1:].iterrows():
            if r.Low<=stp: ex=stp; break
            if r.High>=e+10*R: ex=e+10*R; break
        rows.setdefault("5-min ORB long, green 1st bar (60d only)",[]).append(ex/e-1-RT)
print("Per-trade results, all three stocks pooled (after 0.10% round-trip cost):")
for k,v in rows.items(): summ(k,v)
