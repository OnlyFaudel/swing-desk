import pandas as pd, numpy as np, json, collections
D=pd.read_pickle('/tmp/sz/daily_max.pkl'); C=D['Close']; spy=C['SPY']; idx=C.index; cost=0.002
P=json.load(open('/home/claude/swing-desk/memory/price_events.json'))
types=collections.Counter(e['type'] for e in P); print({k:v for k,v in types.most_common()})
L=json.load(open('/home/claude/swing-desk/research/trial_ledger.json'))['strategies']
res=[]
for ty,_ in types.most_common():
    if ty.startswith('macro_'): continue  # macro moves were tested in macro_drivers
    ev=[e for e in P if e['type']==ty]
    rows=[]; last={}
    for e in sorted(ev,key=lambda e:e['date']):
        t=e['ticker']
        if t not in C: continue
        i=idx.searchsorted(pd.Timestamp(e['date']))+1  # next close
        if i+10>=len(idx) or i<1 or (t in last and i-last[t]<10): continue
        a,b=C[t].iloc[i],C[t].iloc[i+10]
        if not(np.isfinite(a) and np.isfinite(b)) or a<3: continue
        last[t]=i; rows.append((idx[i].year,(b/a-1)-(spy.iloc[i+10]/spy.iloc[i]-1)-cost))
    x=pd.DataFrame(rows,columns=['yr','x'])
    a,b=x[x.yr<=2018].x,x[x.yr>=2019].x
    f=lambda y:(y.mean()*100, y.mean()/y.std()*np.sqrt(len(y)) if len(y)>2 else 0, len(y))
    res.append((ty,)+f(a)+f(b))
print(f'{"price event -> next close, 10 days vs S&P":34s} {"2008-18":>22s} {"2019-26":>22s}')
for ty,am,at,an,bm,bt,bn in res:
    flag='  <- both eras positive' if am>0 and bm>0 and at>1 and bt>1 else ('  <- both negative' if am<0 and bm<0 and at<-1 and bt<-1 else '')
    print(f'{ty:34s} {am:+6.2f}% t{at:5.1f} n{an:5d} | {bm:+6.2f}% t{bt:5.1f} n{bn:5d}{flag}')
