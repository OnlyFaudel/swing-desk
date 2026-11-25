import pandas as pd, numpy as np, json, warnings; warnings.filterwarnings("ignore")
W=pd.read_pickle('/tmp/wide/wide.pkl'); O,H,Lo,C,V=[W[k].copy() for k in ('Open','High','Low','Close','Volume')]
N=pd.read_pickle('/tmp/sz/daily_max.pkl')
for t in N['Close'].columns:
    if t not in C.columns and all(k in N.columns.get_level_values(0) for k in ('Open','Low')):
        for D,k in ((O,'Open'),(Lo,'Low'),(C,'Close'),(V,'Volume')): D[t]=N[k][t].reindex(C.index)
NUC=[t for t in ["CCJ","NXE","UEC","DNN","UUUU","LEU","BWXT","CEG","VST","TLN"] if t in C]
REL=[t for t in json.load(open('/tmp/cfg.json'))['panic_rebound']['related_universe'] if t in C]
U=NUC+REL
idx=C.index; I={d:i for i,d in enumerate(idx)}
dv=(C*V).rolling(20).mean(); OK=(C>3)&(dv>5e6)
COST=0.002
# market holidays = weekdays missing from SPY's trading calendar
bd=pd.bdate_range(idx[0],idx[-1]); hol=[d for d in bd if d not in I and d.year>=2007]
def tg_day(y):
    d=pd.Timestamp(y,11,1); return d+pd.Timedelta(days=(3-d.dayofweek)%7+21)
TG=[tg_day(y) for y in range(2007,2026)]
def era(d): return '2007-18' if d.year<=2018 else '2019-25'
def prev_i(d):  # last trading index before date d
    return idx.searchsorted(d)-1
def summarize(rows,name,ctrl=None):
    df=pd.DataFrame(rows)
    if df.empty: print(name,'no trades'); return
    df['era']=df.d.map(era)
    per=df.groupby(['era','d']).r.mean().reset_index()
    out=[]
    for e,g in per.groupby('era'):
        m=g.r.mean()*100; s=g.r.std(ddof=1)*100 if len(g)>1 else np.nan; t=m/(s/np.sqrt(len(g))) if len(g)>1 and s>0 else np.nan
        sub=df[df.era==e]; out.append(f"{e}: {len(g)} events/{len(sub)} buys, avg {sub.r.mean()*100:+.2f}%/buy, per-event {m:+.2f}% (t {t:.1f}), up {(sub.r>0).mean()*100:.0f}%")
    line=f"{name}\n   "+"\n   ".join(out)
    if ctrl is not None:
        cdf=pd.DataFrame(ctrl); cdf['era']=cdf.d.map(era)
        line+="\n   ordinary weeks, same trade: "+", ".join(f"{e} {g.r.mean()*100:+.2f}%/buy (n {len(g)})" for e,g in cdf.groupby('era'))
    print(line, flush=True)


# helper at k% under prior close, exit at close of index xi
def limit_trade(t,i,k,xi):
    pc=C[t].iloc[i-1]; L=pc*(1-k); o=O[t].iloc[i]; lo=Lo[t].iloc[i]
    if any(np.isnan(v) for v in (pc,o,lo)) or not OK[t].iloc[i-1]: return None
    if o<=L: f=o
    elif lo<=L: f=L
    else: return None
    x=C[t].iloc[xi]
    if np.isnan(x): return None
    return x/f-1-COST-(C['SPY'].iloc[xi]/C['SPY'].iloc[i-1]-1)*0  # raw return; S&P comparison via control
