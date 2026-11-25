import pandas as pd, numpy as np
d=pd.read_pickle('/tmp/sz/daily_max.pkl'); C=d['Close']; V=d['Volume']; spy=C['SPY']
spec=[t for t in ['OKLO','SMR','NNE','LTBR','ASPI','NUSC','UROY','URG','EU','LEU'] if t in C]
print('speculative names present:',spec)
r5=C/C.shift(5)-1; dv=(C*V).rolling(20).mean(); rows=[]
for t in [x for x in C.columns if x!='SPY']:
    c=C[t].values; last=-99
    for i in range(30,len(c)-11):
        if np.isnan(c[i]) or c[i]<3 or not(dv[t].iloc[i]>5e6) or i-last<10 or not(r5[t].iloc[i]<=-0.15): continue
        last=i; ex=next((k for k in range(1,11) if c[i+k]>=c[i]*1.10),10)
        rows.append((C.index[i],t,t in spec,c[i+ex]/c[i]-1-(spy.iloc[i+ex]/spy.iloc[i]-1)-0.002, r5[t].iloc[i]))
r=pd.DataFrame(rows,columns=['d','t','spec','ret','r5'])
for per,(a,b) in {'2019-22':('2019','2023'),'2023-26':('2023','2027')}.items():
    x=r[(r.d>=a)&(r.d<b)]
    for k,g in x.groupby('spec'):
        print(f"{per} {'speculative reactor/fuel names' if k else 'everything else':32s}: sharp-drop trades {len(g):4d} avg {g.ret.mean()*100:+.2f}% median {g.ret.median()*100:+.2f}% worst5% {g.ret.quantile(.05)*100:.1f}% up {(g.ret>0).mean()*100:.0f}%")
print(r[r.spec].groupby('t').ret.agg(['count','mean']).round(3))
