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

# ---------- A. Claim check: does the market dip during Thanksgiving week?
print("A. Thanksgiving week, S&P 500 and our nuclear stocks (2007-2025):")
rows=[]
for tg in TG:
    i_mon=idx.searchsorted(tg-pd.Timedelta(days=3)); i_fri=idx.searchsorted(tg+pd.Timedelta(days=1)); i_pf=i_mon-1; i_tue=i_mon+1
    for t in ['SPY']+NUC:
        if np.isnan(C[t].iloc[i_pf]): continue
        pc=C[t].iloc[i_pf]; low=Lo[t].iloc[i_mon:i_fri+1].min()
        rows.append(dict(y=tg.year,t=t,dip=low/pc-1,week=C[t].iloc[i_fri]/pc-1,tue_fri=C[t].iloc[i_fri]/C[t].iloc[i_tue]-1))
a=pd.DataFrame(rows)
s=a[a.t=='SPY']; n=a[a.t!='SPY']
print(f"   S&P: dipped 1%+ below last Friday's close at some point in the week {(s.dip<=-0.01).mean()*100:.0f}% of years, 2%+ {(s.dip<=-0.02).mean()*100:.0f}%; week ended up {(s.week>0).mean()*100:.0f}% of years")
print(f"   Nuclear stocks: dipped 3%+ {(n.dip<=-0.03).mean()*100:.0f}% of stock-years, 5%+ {(n.dip<=-0.05).mean()*100:.0f}%; week ended up {(n.week>0).mean()*100:.0f}%")
# control: same stats in ordinary 4.5-day weeks (Mon-Fri, non-holiday weeks)
crow=[]
for i in range(260,len(idx)-5):
    d=idx[i]
    if d.dayofweek!=0 or idx[i+4]-d!=pd.Timedelta(days=4) or d.month==11 and d.day>=20 and d.day<=27: continue
    for t in ['SPY']+NUC:
        pc=C[t].iloc[i-1]
        if np.isnan(pc): continue
        crow.append(dict(t=t,dip=Lo[t].iloc[i:i+5].min()/pc-1,week=C[t].iloc[i+4]/pc-1))
c=pd.DataFrame(crow); cs=c[c.t=='SPY']; cn=c[c.t!='SPY']
print(f"   Ordinary weeks for comparison: S&P dips 1%+ {(cs.dip<=-0.01).mean()*100:.0f}%, 2%+ {(cs.dip<=-0.02).mean()*100:.0f}%, up {(cs.week>0).mean()*100:.0f}%; nuclear dips 3%+ {(cn.dip<=-0.03).mean()*100:.0f}%, 5%+ {(cn.dip<=-0.05).mean()*100:.0f}%, up {(cn.week>0).mean()*100:.0f}%")
print("   S&P worst dip each Thanksgiving week:", " ".join(f"{r.y}:{r.dip*100:.1f}" for r in s.itertuples()))

# helper: limit-buy at k% under prior close, exit at close of index xi
def limit_trade(t,i,k,xi):
    pc=C[t].iloc[i-1]; L=pc*(1-k); o=O[t].iloc[i]; lo=Lo[t].iloc[i]
    if any(np.isnan(v) for v in (pc,o,lo)) or not OK[t].iloc[i-1]: return None
    if o<=L: f=o
    elif lo<=L: f=L
    else: return None
    x=C[t].iloc[xi]
    if np.isnan(x): return None
    return x/f-1-COST-(C['SPY'].iloc[xi]/C['SPY'].iloc[i-1]-1)*0  # raw return; S&P comparison via control
# ---------- B. Thanksgiving-week limit dip buys (Mon/Tue/Wed), exit Black Friday close
for k in (0.03,0.05):
    for uni,un in ((NUC,'nuclear'),(U,'nuclear+related')):
        rows=[];ctrl=[]
        for tg in TG:
            i_mon=idx.searchsorted(tg-pd.Timedelta(days=3)); i_fri=idx.searchsorted(tg+pd.Timedelta(days=1))
            for i in range(i_mon,i_fri):
                for t in uni:
                    r=limit_trade(t,i,k,i_fri)
                    if r is not None: rows.append(dict(d=idx[i],t=t,r=r)); break_=None
        # control: same weekday, exit after the same number of sessions, ordinary weeks
        for i in range(260,len(idx)-5):
            d=idx[i]
            if d.dayofweek>2 or (d.month==11 and 20<=d.day<=27): continue
            xi=i+(4-d.dayofweek) if d.dayofweek<3 else i
            xi=min(i+(3-d.dayofweek),len(idx)-1)
            for t in uni:
                r=limit_trade(t,i,k,xi)
                if r is not None: ctrl.append(dict(d=d,t=t,r=r))
        summarize(rows,f"B. Thanksgiving week: limit buy {k*100:.0f}% under yesterday's close (Mon-Wed), sell Black Friday close [{un}]",ctrl)

# ---------- C. Same idea for every market holiday: limit dip in the 3 sessions before, sell at first close after the holiday
for k in (0.03,0.05):
    rows=[];ctrl=[]
    hs=set()
    for h in hol:
        ia=idx.searchsorted(h); 
        if ia>=len(idx) or ia<4: continue
        for i in range(ia-3,ia):
            hs.add(i)
            for t in U:
                r=limit_trade(t,i,k,ia)
                if r is not None: rows.append(dict(d=idx[i],t=t,r=r,h=h))
    for i in range(260,len(idx)-4):
        if i in hs or any(abs(i-idx.searchsorted(h))<6 for h in hol[:0]): continue
        if i in hs: continue
        for t in U:
            r=limit_trade(t,i,k,i+2)
            if r is not None: ctrl.append(dict(d=idx[i],t=t,r=r))
    summarize(rows,f"C. Any market holiday: limit buy {k*100:.0f}% under yesterday's close in the 3 days before, sell first close after [nuclear+related]",ctrl)

# ---------- D. Wednesday before Thanksgiving: stock OPENS down 2%+ -> buy the open, sell Black Friday close
rows=[]
for tg in TG:
    i_w=idx.searchsorted(tg)-1; i_f=idx.searchsorted(tg+pd.Timedelta(days=1))
    for t in U:
        pc,o=C[t].iloc[i_w-1],O[t].iloc[i_w]
        if np.isnan(pc) or np.isnan(o) or not OK[t].iloc[i_w-1] or o/pc-1>-0.02: continue
        rows.append(dict(d=idx[i_w],t=t,r=C[t].iloc[i_f]/o-1-COST))
summarize(rows,"D. Wednesday before Thanksgiving: stock opens down 2%+, buy the open, sell Black Friday close")

# ---------- E. Add to the Thanksgiving trade: bought Tue close; if it dips 3%/5% by Wed or Fri, buy again at the limit; sell Fri close
for k in (0.03,0.05):
    rows=[];base=[]
    for tg in TG:
        i_t=idx.searchsorted(tg)-2; i_w=i_t+1; i_f=idx.searchsorted(tg+pd.Timedelta(days=1))
        for t in NUC:
            e=C[t].iloc[i_t]
            if np.isnan(e) or not OK[t].iloc[i_t]: continue
            base.append(dict(d=idx[i_t],t=t,r=C[t].iloc[i_f]/e-1-COST))
            L=e*(1-k)
            for i in (i_w,i_f):
                if O[t].iloc[i]<=L: f=O[t].iloc[i]
                elif Lo[t].iloc[i]<=L: f=L
                else: continue
                rows.append(dict(d=idx[i_t],t=t,r=C[t].iloc[i_f]/f-1-COST)); break
    if k==0.03: summarize(base,"E0. The current Thanksgiving trade (buy Tue close, sell Fri close), nuclear, for reference")
    summarize(rows,f"E. Add-on: Thanksgiving trade falls {k*100:.0f}% below the buy, buy the same again at that price, sell Fri close")

# ---------- F. Monday after Thanksgiving: limit dip 3%/5%, hold 5 sessions
for k in (0.03,0.05):
    rows=[];ctrl=[]
    mons=set()
    for tg in TG:
        i=idx.searchsorted(tg+pd.Timedelta(days=4)); mons.add(i)
        for t in U:
            r=limit_trade(t,i,k,min(i+5,len(idx)-1))
            if r is not None: rows.append(dict(d=idx[i],t=t,r=r))
    for i in range(260,len(idx)-6):
        if idx[i].dayofweek!=0 or i in mons: continue
        for t in U:
            r=limit_trade(t,i,k,i+5)
            if r is not None: ctrl.append(dict(d=idx[i],t=t,r=r))
    summarize(rows,f"F. Monday after Thanksgiving: limit buy {k*100:.0f}% under Friday's close, hold 5 sessions",ctrl)
