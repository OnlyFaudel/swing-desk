import pickle, pandas as pd, numpy as np, warnings
warnings.filterwarnings("ignore")
TR=pickle.load(open("patient_trades.pkl","rb"))   # ticker -> [(entry_ts, exit_ts, ret, R)], cost 0.1% included
ALL=sorted(TR)
start=min(x[0] for v in TR.values() for x in v); end=max(x[1] for v in TR.values() for x in v)
def shrunk(t, asof, weeks=26, prior=0.2, k=10):
    xs=[x[2]*100 for x in TR[t] if asof-pd.Timedelta(weeks=weeks) <= x[1] < asof]
    return (prior*k+sum(xs))/(k+len(xs)), len(xs)
def run(universe, slots, select_n=None, force=("CCJ",), extra_cost=0.0, warm=26):
    events=sorted([(x[0],x[1],x[2]-extra_cost/100,t) for t in universe for x in TR[t]])
    eq=1000.0; open_=[]; curve=[]; sel_cache={}; taken=0
    t0=start+pd.Timedelta(weeks=warm) if select_n else start
    def selected(ts):
        wk=(ts - pd.Timedelta(days=ts.weekday())).normalize()
        if wk not in sel_cache:
            ranks=sorted(((shrunk(t,wk)[0],t) for t in universe if t not in force),reverse=True)
            sel_cache[wk]=set(force)|{t for _,t in ranks[:select_n]}
        return sel_cache[wk]
    for en,ex,r,t in events:
        if en<t0: continue
        # close positions that exited before this entry
        for p in sorted([p for p in open_ if p[1]<=en],key=lambda p:p[1]):
            eq+=p[2]*p[3]; curve.append((p[1],eq)); open_.remove(p)
        if len(open_)>=slots or any(p[4]==t for p in open_): continue
        if select_n and t not in selected(en): continue
        size=eq/slots; open_.append((en,ex,size,r,t)); taken+=1
    for p in sorted(open_,key=lambda p:p[1]): eq+=p[2]*p[3]; curve.append((p[1],eq))
    c=pd.Series([v for _,v in curve],index=pd.DatetimeIndex([k for k,_ in curve])).sort_index()
    c=pd.concat([pd.Series([1000.0],index=[t0]),c]); w=c.resample("W-FRI").last().ffill().pct_change().dropna()
    yrs=(c.index[-1]-c.index[0]).days/365.25
    return dict(final=round(c.iloc[-1]),per_year=f"{((c.iloc[-1]/1000)**(1/yrs)-1)*100:+.0f}%",avg_week=f"{w.mean()*100:+.2f}%",
                wk_ge5=f"{(w>=0.05).mean()*100:.0f}%",wk_le_m5=f"{(w<=-0.05).mean()*100:.0f}%",max_dd=f"{(c/c.cummax()-1).min()*100:.0f}%",
                trades_wk=round(taken/((c.index[-1]-c.index[0]).days/7),1),weeks=len(w))
CHIPS_NUKE=[t for t in ALL if t not in ("SPY","QQQ","XLU","SMH","URA")]
tests={"CCJ+MU+PLTR, 2 slots":(["CCJ","MU","PLTR"],2,None),
       "CCJ+TSM+ETN, 2 slots":(["CCJ","TSM","ETN"],2,None),
       "CCJ+TSM+ETN, 3 slots":(["CCJ","TSM","ETN"],3,None),
       "Bot picks top 2 + CCJ weekly, 2 slots":(CHIPS_NUKE,2,2),
       "Bot picks top 2 + CCJ weekly, 3 slots":(CHIPS_NUKE,3,2),
       "Bot picks top 4 + CCJ weekly, 3 slots":(CHIPS_NUKE,3,4),
       "Bot picks top 4 + CCJ weekly, 4 slots":(CHIPS_NUKE,4,4),
       "All 20 stocks, first come, 3 slots":(CHIPS_NUKE,3,None)}
print("Last ~18 months (first 6 months used only to rank stocks), 0.1% costs:")
for name,(u,s,n) in tests.items():
    print(f"  {name:40s}", run(u,s,n,warm=26))
print("\nSame, at 0.2% round-trip costs:")
for name in ["CCJ+TSM+ETN, 2 slots","Bot picks top 2 + CCJ weekly, 2 slots","Bot picks top 4 + CCJ weekly, 3 slots"]:
    u,s,n=tests[name]; print(f"  {name:40s}", run(u,s,n,extra_cost=0.1,warm=26))
