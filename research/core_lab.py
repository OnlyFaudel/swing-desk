import yfinance as yf, pandas as pd, numpy as np
T=["CCJ","MU","PLTR"]
C=yf.download(T+["SPY"],start="2010-01-01",auto_adjust=True,progress=False)["Close"]
def run(tk,start,mode,buf=0.03):
    c=C[tk].loc[start:].dropna(); s200={t:C[t].rolling(200).mean().loc[c.index] for t in tk}
    w={t:1.0 for t in tk}; eq=1.0; curve=[]; hold={t:eq/len(tk) for t in tk}; switches=0
    prev=None
    for i,d in enumerate(c.index):
        if prev is not None:
            for t in tk: hold[t]*= (1+(c[t][d]/c[t][prev]-1)*w[t])   # sleeve value; unexposed part sits in cash
        eq=sum(hold.values()); curve.append(eq)
        if mode!="hold" and d.weekday()==4:   # weekly check on Fridays
            for t in tk:
                px,m=c[t][d],s200[t][d]
                if np.isnan(m): continue
                low = 0.5 if mode=="half" else 0.0
                if w[t]==1 and px<m*(1-buf): w[t]=low; switches+=1
                elif w[t]<1 and px>m*(1+buf): w[t]=1.0; switches+=1
        if d.month!=(c.index[i+1].month if i+1<len(c) else d.month):  # monthly rebalance
            tot=sum(hold.values()); hold={t:tot/len(tk) for t in tk}
        prev=d
    s=pd.Series(curve,index=c.index); yrs=len(s)/252
    return f"cagr {((s.iloc[-1])**(1/yrs)-1)*100:5.1f}%  maxDD {(s/s.cummax()-1).min()*100:6.1f}%  switches/yr {switches/yrs:4.1f}"
for tk,st in [(["CCJ","MU"],"2011-01-01"),(T,"2021-06-01")]:
    print(tk,st)
    for m in ["hold","half","out"]: print(f"   {m:5s}", run(tk,st,m))
