import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
d=pd.read_pickle('/tmp/sz/daily_max.pkl'); C=d['Close']; V=d['Volume']; spy=C['SPY']; S=spy.pct_change()
names=[t for t in C.columns if t!='SPY']
R=C.pct_change(); hi20=C.rolling(20).max(); r5=C/C.shift(5)-1; dv=(C*V).rolling(20).mean()
ok=(C>3)&(dv>5e6)
panic=(S<=-0.02).values[:,None]&(R<=-0.03)&(C<=hi20*0.85)&ok
sharp=(r5<=-0.15)&ok
rows=[]
for j,t in enumerate(names):
    c=C[t].values
    for i in np.where(panic[t].values | sharp[t].values)[0]:
        if i+12>=len(c) or np.isnan(c[i]): continue
        p,s_=bool(panic[t].values[i]),bool(sharp[t].values[i])
        def ret(e,h):  # buy close e, hold h, vs S&P, cost
            return c[e+h]/c[e]-1-(spy.values[e+h]/spy.values[e]-1)-0.002
        rows.append(dict(d=C.index[i],t=t,kind='both' if p and s_ else ('panic only' if p else 'sharp only'),
                         r6=ret(i,6),r10=ret(i,10),
                         d2_up=c[i+1]>c[i], r6_d2=ret(i+1,6)))
r=pd.DataFrame(rows)
# one per stock per 10 days within kind
r=r.sort_values('d'); keep=[];last={}
for _,x in r.iterrows():
    k=(x.t,x.kind)
    if k not in last or (x.d-last[k]).days>14: keep.append(x); last[k]=x.d
r=pd.DataFrame(keep)
for era,(a,b) in {'00-07':('2000','2008'),'08-18':('2008','2019'),'19-26':('2019','2027')}.items():
    x=r[(r.d>=a)&(r.d<b)]
    print(era,' | '.join(f"{k}: 6d {g.r6.mean()*100:+.2f}% 10d {g.r10.mean()*100:+.2f}% n{len(g)}" for k,g in x.groupby('kind')))
    pk=x[x.kind!='sharp only']
    print('    panic trades, wait for day 2: day 2 up -> buy day-2 close %+.2f%% (n%d) | day 2 down -> %+.2f%% (n%d) | buy day 1 as live %+.2f%%'%(
        pk[pk.d2_up].r6_d2.mean()*100,pk.d2_up.sum(),pk[~pk.d2_up].r6_d2.mean()*100,(~pk.d2_up).sum(),pk.r6.mean()*100))
