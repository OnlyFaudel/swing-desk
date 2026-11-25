import pandas as pd, numpy as np
d=pd.read_pickle('/tmp/sz/daily_max.pkl'); C=d['Close']; V=d['Volume']; spy=C['SPY']
r5=C/C.shift(5)-1; dv=(C*V).rolling(20).mean(); rows=[]
for t in [x for x in C.columns if x!='SPY']:
    c=C[t].values; last=-99
    for i in range(30,len(c)-11):
        if np.isnan(c[i]) or c[i]<3 or not(dv[t].iloc[i]>5e6) or i-last<10 or not(r5[t].iloc[i]<=-0.15): continue
        last=i; ex=next((k for k in range(1,11) if c[i+k]>=c[i]*1.10),10)
        rows.append((C.index[i],c[i+ex]/c[i]-1-(spy.iloc[i+ex]/spy.iloc[i]-1)-0.002))
r=pd.DataFrame(rows,columns=['d','ret']); r['wd']=r.d.dt.day_name().str[:3]
for era,(a,b) in {'00-07':('2000','2008'),'08-18':('2008','2019'),'19-26':('2019','2027')}.items():
    x=r[(r.d>=a)&(r.d<b)]
    print(era,' '.join(f"{w}: {g.ret.mean()*100:+.2f}% ({len(g)})" for w,g in x.groupby('wd')))
