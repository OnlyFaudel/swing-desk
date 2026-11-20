"""Signal Lab: does an idea add value on top of the base rule, in BOTH halves of history?
Base rule: buy when price > MA(trend) and RSI(n) < thr; sell when price < MA(trend).
Run: python research/signal_lab.py"""
import yfinance as yf, pandas as pd, numpy as np, itertools, json, sys
T=["CCJ","MU","PLTR"]; SECTOR={"CCJ":"URA","MU":"SMH","PLTR":"IGV"}
X=["SPY","^VIX","^VIX3M","URA","SMH","IGV"]
raw=yf.download(T+X,start="2009-01-01",auto_adjust=True,progress=False)
C=raw["Close"]; H=raw["High"]; L=raw["Low"]
def rsi(c,n):
    d=c.diff(); up=d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean(); dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean()
    return 100-100/(1+up/dn.replace(0,np.nan))
atr={t:(pd.concat([H[t]-L[t],(H[t]-C[t].shift()).abs(),(L[t]-C[t].shift()).abs()],axis=1).max(axis=1)).rolling(14).mean() for t in T}
spy200=C["SPY"]>C["SPY"].rolling(200).mean()
vix_ok=C["^VIX"]<25
contango=C["^VIX"]<C["^VIX3M"]
rs={t:(C[t]/C[SECTOR[t]]).pct_change(63)>0 for t in T}
tom=pd.Series(C.index.day,index=C.index)
tom=(tom>=25)|(tom<=3)
ma_cache={}; rsi_cache={}
def sim(start,end,n=2,thr=15,ma=50,filt=None,size="equal"):
    days=C.loc[start:end].index; tk=[t for t in T if C[t].loc[:start].dropna().shape[0]>250]
    cash=1000.0; pos={}; curve=[]
    for t in tk:
        ma_cache.setdefault((t,ma),C[t].rolling(ma).mean()); rsi_cache.setdefault((t,n),rsi(C[t],n))
    for d in days:
        for t in list(pos):
            if C[t][d]<ma_cache[(t,ma)][d]:
                cash+=pos.pop(t)*C[t][d]*0.9995
        for t in tk:
            if t in pos or np.isnan(C[t][d]): continue
            if C[t][d]>ma_cache[(t,ma)][d] and rsi_cache[(t,n)][d]<thr and (filt is None or filt(t,d)):
                eq=cash+sum(s*C[k][d] for k,s in pos.items())
                if size=="vol":   # risk the same 1.5x ATR stop distance: 2% of equity
                    amt=min(cash,eq*0.02/(1.5*atr[t][d]/C[t][d]),eq/len(tk)*1.5)
                else: amt=min(cash,eq/len(tk))
                if amt>5: cash-=amt; pos[t]=amt*0.9995/C[t][d]
        curve.append(cash+sum(s*C[k][d] for k,s in pos.items()))
    c=pd.Series(curve,index=days); r=c.pct_change().dropna(); yrs=len(c)/252
    return dict(cagr=round(((c.iloc[-1]/1000)**(1/yrs)-1)*100,1),dd=round((c/c.cummax()-1).min()*100,1),
                sharpe=round(r.mean()/r.std()*np.sqrt(252),2) if r.std()>0 else 0)
P1,P2=("2012-01-01","2020-12-31"),("2021-01-01","2026-12-31")
out={}
# 1) RSI / trend parameter search: pick best on P1, see how it does on P2
grid=list(itertools.product([2,3,5],[5,10,15,20,30],[20,50,100,200]))
res=[]
for n,thr,ma in grid:
    a=sim(*P1,n=n,thr=thr,ma=ma); b=sim(*P2,n=n,thr=thr,ma=ma); res.append((n,thr,ma,a,b))
res.sort(key=lambda x:-x[3]["sharpe"])
base=[r for r in res if r[:3]==(2,15,50)][0]
rank_p2=sorted(res,key=lambda x:-x[4]["sharpe"])
print("PARAM SEARCH (n, threshold, trend MA): best 5 on 2012-2020 and how they did 2021-2026")
for r in res[:5]: print(" ",r[:3],"P1",r[3],"P2",r[4],"P2 rank",[x[:3] for x in rank_p2].index(r[:3])+1,"/",len(res))
print("  base (2,15,50) P1",base[3],"P2",base[4],"P2 rank",[x[:3] for x in rank_p2].index((2,15,50))+1)
print("  median P2 sharpe across all",np.median([r[4]["sharpe"] for r in res]))
out["param"]={"best_p1":[r[:3] for r in res[:5]],"base":base[3:]}
# 2) Filters / sizing on top of base
tests={"base":None,"market uptrend (SPY>200d)":lambda t,d:spy200[d],"VIX < 25":lambda t,d:vix_ok[d],
       "VIX contango":lambda t,d:contango[d],"beats its sector (3mo)":lambda t,d:rs[t][d],"turn of month":lambda t,d:tom[d]}
print("\nFILTERS on base rule:  P1=2012-2020 (CCJ,MU)  P2=2021-2026 (CCJ,MU,PLTR)")
rows=[]
for k,f in tests.items():
    a=sim(*P1,filt=f); b=sim(*P2,filt=f); rows.append((k,a,b)); print(f"  {k:28s} P1 {a}  P2 {b}")
a=sim(*P1,size="vol"); b=sim(*P2,size="vol"); rows.append(("volatility-scaled sizing",a,b)); print(f"  {'volatility-scaled sizing':28s} P1 {a}  P2 {b}")
json.dump({"filters":[{"name":k,"p1":a,"p2":b} for k,a,b in rows]},open("signal_lab_results.json","w"),indent=1)
