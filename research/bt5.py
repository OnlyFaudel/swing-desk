import yfinance as yf, pandas as pd, numpy as np, itertools, sys
from strat_core import add_ind
T=["CCJ","MU","PLTR"]
raw=yf.download(T,start="2013-01-01",auto_adjust=True,progress=False)
D={t:add_ind(raw.xs(t,axis=1,level=1).dropna()) for t in T}
def run(stop_kind, target=0.05, entry="rsi2", lock=True, brake=-0.06, start="2015-01-01", maxhold=10):
    days=D["CCJ"].loc[start:].index
    cash=1000.0; pos={}; trades=[]; curve=[]; wk=None; wk_start=1000; locked=False
    for d in days:
        eqo=cash+sum(p["sh"]*D[t].loc[:d].Close.iloc[-2] for t,p in pos.items())
        w=d.isocalendar()[:2]
        if w!=wk: wk=w; wk_start=eqo; locked=False
        # exits intraday
        for t in list(pos):
            if d not in D[t].index: continue
            r=D[t].loc[d]; p=pos[t]; p["days"]+=1; px=None
            if r.Open<=p["stop"]: px,why=r.Open,"stop"
            elif r.Low<=p["stop"]: px,why=p["stop"],"stop"
            elif r.Open>=p["tgt"]: px,why=r.Open,"target"
            elif r.High>=p["tgt"]: px,why=p["tgt"],"target"
            elif p["days"]>=maxhold: px,why=r.Close,"time"
            if px is not None:
                cash+=p["sh"]*px*0.9995; trades.append((t,px/p["e"]-1,why)); del pos[t]
        eq=cash+sum(p["sh"]*D[t].Close.get(d,np.nan) for t,p in pos.items() if d in D[t].index)
        wr=eq/wk_start-1
        if lock and (wr>=0.05 or wr<=brake) and not locked:
            for t,p in list(pos.items()):
                px=D[t].Close.get(d); cash+=p["sh"]*px*0.9995; trades.append((t,px/p["e"]-1,"weeklock")); del pos[t]
            locked=True
        if not locked:
            for t in T:
                if t in pos or d not in D[t].index: continue
                r=D[t].loc[d]
                if r.isna().any(): continue
                ok = (r.Close>r.sma50 and r.rsi2<15) if entry=="rsi2" else (r.Close>r.sma50 and r.Close>=r.hi20)
                if ok:
                    eqn=cash+sum(p["sh"]*D[k].Close.get(d,p["e"]) for k,p in pos.items())
                    amt=min(cash,eqn/3)
                    if amt<5: continue
                    s = 0.025 if stop_kind=="2.5%" else 0.05 if stop_kind=="5%" else min(0.12,1.5*r.atr/r.Close)
                    cash-=amt; pos[t]={"sh":amt*0.9995/r.Close,"e":r.Close,"stop":r.Close*(1-s),"tgt":r.Close*(1+target),"days":0}
        curve.append((d,cash+sum(p["sh"]*D[t].Close.get(d,p["e"]) for t,p in pos.items())))
    c=pd.Series(dict(curve)); wkly=c.resample("W-FRI").last().pct_change().dropna()
    tr=pd.DataFrame(trades,columns=["t","r","why"]); yrs=(c.index[-1]-c.index[0]).days/365.25
    return dict(stop=stop_kind,entry=entry,lock=lock,final=round(c.iloc[-1]),cagr=round(((c.iloc[-1]/1000)**(1/yrs)-1)*100,1),
        maxdd=round((c/c.cummax()-1).min()*100,1),trades=len(tr),win=round((tr.r>0).mean()*100),
        wk_ge5=round((wkly>=0.049).mean()*100),wk_le_m5=round((wkly<=-0.05).mean()*100),wk_pos=round((wkly>0).mean()*100),
        bh=None)
rows=[run(s,entry=e,lock=l) for s,e,l in itertools.product(["2.5%","5%","1.5ATR"],["rsi2","breakout"],[True,False])]
bh=sum(D[t].Close.loc["2015-01-01":] / D[t].Close.loc["2015-01-01":].iloc[0] for t in ["CCJ","MU"])/2
print(pd.DataFrame(rows).drop(columns="bh").to_string(index=False))
# buy-hold equal weight (PLTR joins late; use CCJ+MU from 2015 and all 3 from 2021)
for st in ["2015-01-01","2021-01-01"]:
    tk=["CCJ","MU"] if st<"2020" else T
    c=sum(D[t].Close.loc[st:]/D[t].Close.loc[st:].iloc[0] for t in tk)/len(tk)*1000
    wk=c.resample("W-FRI").last().pct_change().dropna(); yrs=(c.index[-1]-c.index[0]).days/365.25
    print("B&H",tk,st,"final",round(c.iloc[-1]),"cagr",round(((c.iloc[-1]/1000)**(1/yrs)-1)*100,1),"maxdd",round((c/c.cummax()-1).min()*100,1),"wk>=5%",round((wk>=.049).mean()*100),"wk<=-5%",round((wk<=-.05).mean()*100))
print("--- 2021+ all three ---")
print(pd.DataFrame([run(s,entry=e,lock=True,start="2021-01-01") for s in ["2.5%","5%","1.5ATR"] for e in ["rsi2","breakout"]]).drop(columns="bh").to_string(index=False))
