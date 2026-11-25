import pandas as pd, numpy as np
E=pd.read_pickle('/tmp/sz/earn_events.pkl'); E['d']=pd.to_datetime(E.d)
C=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']; spy=C['SPY']
grp={'miners':['CCJ','UEC','DNN','UUUU','NXE'],'power':['CEG','VST','TLN'],'fuel':['LEU','BWXT']}
G={t:g for g,ts in grp.items() for t in ts}
print(E.head(2).to_dict('records')); print('events',len(E),E.d.min().date(),E.d.max().date())
rows=[]
for _,e in E.iterrows():
    if e.t not in G or pd.isna(e.r0): continue
    i=C.index.searchsorted(e.d)
    if i+6>=len(C) or i<1: continue
    for p in grp[G[e.t]]:
        if p==e.t or pd.isna(C[p].iloc[i-1]): continue
        same=(C[p].iloc[i]/C[p].iloc[i-1]-1)-(spy.iloc[i]/spy.iloc[i-1]-1)
        nxt=(C[p].iloc[i+5]/C[p].iloc[i]-1)-(spy.iloc[i+5]/spy.iloc[i]-1)-0.002   # buy peer at the reaction-day close
        rows.append((e.d,e.t,p,e.r0/100 if abs(e.r0)>1 else e.r0,same,nxt))
r=pd.DataFrame(rows,columns=['d','rep','peer','r0','same','next5'])
for era,(a,b) in {'2010-18':('2010','2019'),'2019-26':('2019','2027')}.items():
    x=r[(r.d>=a)&(r.d<b)]
    for lab,m in (('reporter jumps 5%+',x.r0>=0.05),('reporter drops 5%+',x.r0<=-0.05)):
        y=x[m]; lag=y[(y.same<y.r0/3)] if 'jumps' in lab else y[(y.same>y.r0/3)]
        print(f"{era} {lab:20s} peers same day {y.same.mean()*100:+.2f}% | peers next 5d {y.next5.mean()*100:+.2f}% (t {y.next5.mean()/y.next5.std()*np.sqrt(len(y)):+.1f}) n{len(y)} | peers that lagged the reporter: next 5d {lag.next5.mean()*100:+.2f}% n{len(lag)}")
