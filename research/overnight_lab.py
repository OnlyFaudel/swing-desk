import yfinance as yf, pandas as pd, numpy as np
T=["CCJ","MU","PLTR","SPY"]
D=yf.download(T,start="2015-01-01",auto_adjust=False,progress=False)   # unadjusted O/C for true overnight; add back dividends approx ignored
for t in T:
    o=D["Open"][t].dropna(); c=D["Close"][t].dropna(); idx=o.index.intersection(c.index); o,c=o[idx],c[idx]
    on=(o/c.shift()-1).dropna(); intra=(c/o-1)[on.index]
    s50=c.rolling(50).mean().shift()[on.index]; up=(c.shift()[on.index]>s50)
    try:
        ed=yf.Ticker(t).get_earnings_dates(limit=60).index.tz_localize(None).normalize() if t!="SPY" else pd.DatetimeIndex([])
    except Exception: ed=pd.DatetimeIndex([])
    near=on.index.isin(ed)|on.index.isin(ed+pd.offsets.BDay(1))
    print(f"\n{t}: overnight vs intraday, per year (avg %/day, before costs)")
    for y,g in on.groupby(on.index.year):
        i=intra[g.index]
        print(f"  {y}: overnight {g.mean()*100:+.3f}% (win {100*(g>0).mean():.0f}%)  intraday {i.mean()*100:+.3f}%  n={len(g)}")
    for cost in [0.001,0.002,0.003]:
        r=on-cost
        print(f"  all yrs cost {cost*100:.1f}% RT: avg {r.mean()*100:+.3f}%/night  compounded {((1+r).prod()-1)*100:,.0f}%   | ex-earnings {((on[~near]-cost)).mean()*100:+.3f}%  | uptrend-only {((on[up]-cost)).mean()*100:+.3f}%")
    print(f"  buy&hold compounded {(c.iloc[-1]/c.iloc[0]-1)*100:,.0f}%   worst single night {on.min()*100:.1f}%  worst night ex-earnings {on[~near].min()*100:.1f}%")
