import yfinance as yf, pandas as pd, numpy as np
from strat_core import add_ind
T=["CCJ","MU","PLTR"]
raw=yf.download(T,start="2013-01-01",auto_adjust=True,progress=False)
D={t:add_ind(raw.xs(t,axis=1,level=1).dropna()) for t in T}
for t in T: D[t]["sma20"]=D[t].Close.rolling(20).mean()
def run(mode, lock=True, brake=-0.06, start="2015-01-01", trail=None):
    tk=[t for t in T if D[t].index[0]<pd.Timestamp(start)-pd.Timedelta(days=120)]
    days=D["CCJ"].loc[start:].index; cash=1000.0; pos={}; curve=[]; wk=None; locked=False; ntr=0; wins=0
    prev_eq=1000
    for d in days:
        w=d.isocalendar()[:2]
        if w!=wk: wk=w; wk_start=prev_eq; locked=False
        for t in list(pos):
            r=D[t].loc[d]; p=pos[t]; p["hi"]=max(p["hi"],r.Close)
            out = r.Close<r.sma50 if mode=="trend" else (r.Close<r.sma50 or (trail and r.Close<p["hi"]-trail*r.atr))
            if mode=="pull" and trail is None: out = r.Close<r.sma50
            if out:
                cash+=p["sh"]*r.Close*0.9995; ntr+=1; wins+=r.Close>p["e"]; del pos[t]
        eq=cash+sum(p["sh"]*D[t].Close[d] for t,p in pos.items()); wr=eq/wk_start-1
        if lock and not locked and (wr>=0.05 or wr<=brake):
            for t,p in list(pos.items()):
                px=D[t].Close[d]; cash+=p["sh"]*px*0.9995; ntr+=1; wins+=px>p["e"]; del pos[t]
            locked=True
        if not locked:
            for t in tk:
                if t in pos: continue
                r=D[t].loc[d]
                if r.isna().any(): continue
                ok = r.Close>r.sma50 if mode=="trend" else (r.Close>r.sma50 and r.rsi2<15)
                if ok:
                    eqn=cash+sum(p["sh"]*D[k].Close[d] for k,p in pos.items()); amt=min(cash,eqn/len(tk))
                    if amt>5: cash-=amt; pos[t]={"sh":amt*0.9995/r.Close,"e":r.Close,"hi":r.Close}
        prev_eq=cash+sum(p["sh"]*D[t].Close[d] for t,p in pos.items()); curve.append((d,prev_eq))
    c=pd.Series(dict(curve)); wkr=c.resample("W-FRI").last().pct_change().dropna(); yrs=(c.index[-1]-c.index[0]).days/365.25
    return dict(mode=mode,trail=trail,lock=lock,start=start,final=round(c.iloc[-1]),cagr=round(((c.iloc[-1]/1000)**(1/yrs)-1)*100,1),
      maxdd=round((c/c.cummax()-1).min()*100,1),trades=ntr,win=round(wins/max(ntr,1)*100),wk_ge5=round((wkr>=0.049).mean()*100),
      wk_le_m5=round((wkr<=-0.05).mean()*100),wk_pos=round((wkr>0).mean()*100),avg_wk=round(wkr.mean()*100,2))
rows=[]
for st in ["2015-01-01","2021-01-01"]:
    for m,tr in [("trend",None),("pull",None),("pull",3)]:
        for lk in [True,False]: rows.append(run(m,lock=lk,start=st,trail=tr))
print(pd.DataFrame(rows).to_string(index=False))
