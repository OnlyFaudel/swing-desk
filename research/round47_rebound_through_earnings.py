import pandas as pd, numpy as np
E=pd.read_pickle('/tmp/sz/earn_events.pkl'); E['d']=pd.to_datetime(E.d)
d=pd.read_pickle('/tmp/sz/daily_max.pkl'); C=d['Close']; V=d['Volume']; spy=C['SPY']; S=spy.pct_change(); R=C.pct_change(); hi20=C.rolling(20).max()
ours=sorted(E.t.unique()); ed={t:set(C.index.searchsorted(E[E.t==t].d)) for t in ours}
r5=C/C.shift(5)-1; rows=[]
for t in ours:
    if t not in C: continue
    c=C[t].values; last=-99
    for i in range(30,len(c)-11):
        if np.isnan(c[i]) or i-last<10: continue
        is_p=S.iloc[i]<=-0.02 and R[t].iloc[i]<=-0.03 and c[i]<=hi20[t].iloc[i]*0.85
        is_s=r5[t].iloc[i]<=-0.15
        if not(is_p or is_s): continue
        last=i; N=6 if is_p else 10
        ex=next((k for k in range(1,N+1) if c[i+k]>=c[i]*1.10),N)
        inside=any(i<j<=i+ex for j in ed[t]); justafter=any(i-5<=j<=i for j in ed[t])
        rows.append((C.index[i],t,c[i+ex]/c[i]-1-(spy.iloc[i+ex]/spy.iloc[i]-1)-0.002,inside,justafter))
r=pd.DataFrame(rows,columns=['d','t','ret','earn_inside','drop_was_earnings'])
for era,(a,b) in {'2010-18':('2010','2019'),'2019-26':('2019','2027')}.items():
    x=r[(r.d>=a)&(r.d<b)]
    f=lambda m: f"{x[m].ret.mean()*100:+.2f}% (n {m.sum()}, worst5% {x[m].ret.quantile(.05)*100:.1f}%)"
    print(f"{era}: earnings inside the hold {f(x.earn_inside)} | no earnings {f(~x.earn_inside & ~x.drop_was_earnings)} | the drop itself was an earnings reaction {f(x.drop_was_earnings)}")
