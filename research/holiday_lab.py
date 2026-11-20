import yfinance as yf, pandas as pd, numpy as np, datetime as dt
from convertdate import hebrew
rows=[]
for y in range(1950,2027):
    hy=y+3761   # Hebrew year that begins in autumn of Gregorian year y
    rh=dt.date(*hebrew.to_gregorian(hy,7,1)); yk=dt.date(*hebrew.to_gregorian(hy,7,10))
    rows.append((y,rh,yk))
G=yf.download(["^GSPC","CCJ","MU","PLTR"],start="1949-06-01",auto_adjust=True,progress=False)["Close"]
def stats(sym,start_year=1950):
    c=G[sym].dropna(); out=[]
    for y,rh,yk in rows:
        if y<start_year: continue
        b=c[c.index<pd.Timestamp(rh)]; a=c[c.index<=pd.Timestamp(yk)]
        if len(b)==0 or len(a)==0 or a.index[-1]<=b.index[-1]: continue
        win=a.iloc[-1]/b.iloc[-1]-1
        # Yom Kippur day itself (market open that day): close YK / close day before
        d=c[c.index==pd.Timestamp(yk)]
        ykday=(d.iloc[0]/c[c.index<pd.Timestamp(yk)].iloc[-1]-1) if len(d) else np.nan
        out.append((y,win,ykday, (c.index>b.index[-1])&(c.index<=a.index[-1])))
    w=pd.Series([o[1] for o in out],index=[o[0] for o in out]); k=pd.Series([o[2] for o in out],index=w.index).dropna()
    n_days=int(np.median([o[3].sum() for o in out]))
    r=c.pct_change(n_days).dropna(); r=r[r.index.year>=start_year]
    return w,k,n_days,r
for sym,sy in [("^GSPC",1950),("^GSPC",2000),("CCJ",2000),("MU",2000),("PLTR",2021)]:
    w,k,n,base=stats(sym,sy)
    print(f"\n{sym} {sy}-2026: 'sell Rosh Hashanah, buy Yom Kippur' window (~{n} trading days), {len(w)} years")
    print(f"  window fell in {100*(w<0).mean():.0f}% of years | avg {100*w.mean():+.2f}% | median {100*w.median():+.2f}%")
    print(f"  ANY random {n}-day window fell {100*(base<0).mean():.0f}% of the time | avg {100*base.mean():+.2f}%")
    if len(k): print(f"  Yom Kippur day itself: fell {100*(k<0).mean():.0f}% of {len(k)} years | avg {100*k.mean():+.2f}%")
    if sym=="^GSPC" and sy==2000: print("  last 12 years:", " ".join(f"{y}:{100*v:+.1f}%" for y,v in w.tail(12).items()))
