import pandas as pd, numpy as np, json
D=pd.read_pickle('/tmp/sz/daily_max.pkl'); C,O=D['Close'],D['Open']; spy=C['SPY']; idx=C.index; cost=0.002
H=json.load(open('/home/claude/swing-desk/memory/history_events.json')); A=json.load(open('/home/claude/swing-desk/memory/archive_events.json'))
P=json.load(open('/home/claude/swing-desk/memory/people_events.json')); E=json.load(open('/home/claude/swing-desk/research/event_history.json'))
def fwd(t,d,n,day0=True):
    if t not in C: return None
    i=idx.searchsorted(pd.Timestamp(d))
    if i>=len(idx) or i+n>=len(idx): return None
    if not day0: pass
    a,b=C[t].iloc[i],C[t].iloc[i+n]
    if not(np.isfinite(a) and np.isfinite(b)) or a<1: return None
    return (b/a-1)-(spy.iloc[i+n]/spy.iloc[i]-1)-cost, C[t].iloc[i]/C[t].iloc[i-1]-1 if i>0 else np.nan, idx[i].year
def rep(rows,label,eras=(('08-18',lambda y:y<=2018),('19-26',lambda y:y>=2019))):
    x=pd.DataFrame(rows,columns=['t','d','x','r0','yr']).dropna().drop_duplicates(['t','d'])
    out=[]
    for e,f in eras:
        y=x[x.yr.map(f)].x
        out.append(f'{e} n={len(y):4d} {y.mean()*100:+.2f}% (t {y.mean()/y.std()*np.sqrt(len(y)) if len(y)>2 else 0:.1f})')
    print(f'{label:60s} '+' | '.join(out))
# 1,2 SEC company filings: the day's move >= +3% (cheered) / <= -3% (jeered) -> next 20 days from that close
cu=[e for e in H if e['type']=='company_update' and e['date']>='2007-06-01']
r=[(e['ticker'],e['date'],*fwd(e['ticker'],e['date'],20)) for e in cu if fwd(e['ticker'],e['date'],20)]
rep([x for x in r if x[3]>=0.03],'1 SEC filing day cheered (+3%+) -> 20d vs S&P')
rep([x for x in r if x[3]<=-0.03],'2 SEC filing day jeered (-3% or worse) -> 20d vs S&P')
# 3 opposition news (archive 2019+): halves
half=(('19-22',lambda y:y<=2022),('23-26',lambda y:y>=2023))
op=[e for e in A if e['type']=='news_opposition']; r=[(e['ticker'],e['date'],*fwd(e['ticker'],e['date'],5)) for e in op if fwd(e['ticker'],e['date'],5)]
rep(r,'3 opposition/protest news -> 5d vs S&P (archive 2019+, halves)',half)
# 4 analysts (2024-26)
for ty in ('analyst_upgrade','analyst_downgrade','analyst_new_coverage'):
    ev=[e for e in P if e['type']==ty]; r=[(e['ticker'],e['date'],*fwd(e['ticker'],e['date'],5)) for e in ev if fwd(e['ticker'],e['date'],5)]
    rep(r,f'4 {ty} -> 5d vs S&P (2024-26, halves by year)',(('2024-25',lambda y:y<=2025),('2026',lambda y:y>=2026)))
# 5,6 earnings-day moves (event_history, 2002+): pop >= +8% / drop <= -8%, next 20 / 10 days
rows5,rows6=[],[]
for t,v in E.items():
    for d,mv in v.get('earnings_moves_pct',[]):
        if d<'2007-06-01': continue
        f20=fwd(t,d,20); f10=fwd(t,d,10)
        if mv>=8 and f20: rows5.append((t,d,*f20))
        if mv<=-8 and f10: rows6.append((t,d,*f10))
rep(rows5,'5 earnings pop +8%+ -> next 20d vs S&P (sell into it?)')
rep(rows6,'6 earnings drop -8% or worse -> next 10d vs S&P')
print('--- checks')
EV=json.load(open('/home/claude/swing-desk/memory/events.json'))
cu2=[e for e in EV if e.get('type')=='company_update']
r=[(e['ticker'],e['date'][:10],*fwd(e['ticker'],e['date'][:10],20)) for e in cu2 if fwd(e['ticker'],e['date'][:10],20)]
rep([x for x in r if x[3]>=0.03],'1b company update cheered (+3%), events.json -> 20d vs S&P')
# earnings pops: enter the NEXT day's close (avoids before/after-the-bell date mix-ups), and check how often it worked
rows=[]
for t,v in E.items():
    for d,mv in v.get('earnings_moves_pct',[]):
        if d<'2007-06-01' or mv<8 or t not in C: continue
        i=idx.searchsorted(pd.Timestamp(d))+1
        if i+20>=len(idx): continue
        a,b=C[t].iloc[i],C[t].iloc[i+20]
        if np.isfinite(a) and np.isfinite(b): rows.append((t,d,(b/a-1)-(spy.iloc[i+20]/spy.iloc[i]-1)-cost,mv,idx[i].year))
x=pd.DataFrame(rows,columns=['t','d','x','mv','yr'])
for e,m in (('08-18',x.yr<=2018),('19-26',x.yr>=2019)):
    y=x[m]; print(f'5b earnings pop, bought the NEXT close {e} n={len(y)} {y.x.mean()*100:+.2f}% (t {y.x.mean()/y.x.std()*np.sqrt(len(y)):.1f}, beat S&P {(y.x>0).mean()*100:.0f}%, median {y.x.median()*100:+.2f}%)')
print(x.groupby('t').x.agg(['count','mean']).round(3).to_string())
