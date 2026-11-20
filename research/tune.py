"""Does tuning the rule's settings help on data it hasn't seen? Pick best on 2014-2020, test 2021-2026."""
import yfinance as yf, pandas as pd, numpy as np, itertools
from strat_core import rsi
T=["CCJ","MU","PLTR"]
raw=yf.download(T+["SPY"],start="2012-01-01",auto_adjust=True,progress=False)
C={t:raw["Close"][t].dropna() for t in T}
def sim(t,n,th,ma,a,b):
    c=C[t]; r=rsi(c,n); m=c.rolling(ma).mean()
    c,r,m=c.loc[a:b],r.loc[a:b],m.loc[a:b]
    if len(c)<200: return np.nan
    pos=0; eq=1.0; ent=0
    for i in range(len(c)):
        px=c.iloc[i]
        if pos and px<m.iloc[i]: eq*=px/ent*0.999; pos=0
        elif not pos and px>m.iloc[i] and r.iloc[i]<th: pos=1; ent=px
    if pos: eq*=c.iloc[-1]/ent
    yrs=(c.index[-1]-c.index[0]).days/365.25
    return (eq**(1/yrs)-1)*100
grid=list(itertools.product([2,3,5,14],[5,10,15,20,30,40],[20,50,100,200]))
rows=[]
for t in ["CCJ","MU"]:
    ins={g:sim(t,*g,"2014-01-01","2020-12-31") for g in grid}
    best=max(ins,key=lambda g:ins[g] if not np.isnan(ins[g]) else -99)
    oos_best=sim(t,*best,"2021-01-01","2026-12-31"); oos_def=sim(t,2,15,50,"2021-01-01","2026-12-31")
    allo=[sim(t,*g,"2021-01-01","2026-12-31") for g in grid]
    rank=sorted(allo,reverse=True).index(oos_best)+1
    rows.append(dict(t=t,best_in_sample=best,in_cagr=round(ins[best],1),default_in=round(ins[(2,15,50)],1),
        oos_tuned=round(oos_best,1),oos_default=round(oos_def,1),tuned_rank_oos=f"{rank}/{len(grid)}",oos_median=round(np.nanmedian(allo),1)))
print(pd.DataFrame(rows).to_string(index=False))
