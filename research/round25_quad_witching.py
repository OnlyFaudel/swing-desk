import pandas as pd, numpy as np, datetime as dt
d=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']; ours=['CCJ','UEC','DNN','UUUU','NXE','LEU','BWXT','CEG','VST','TLN']
rel=[t for t in d.columns if t not in ours+['SPY']]
R=d.pct_change(); S=R['SPY']
def tf(y,m):
    x=dt.date(y,m,15)
    while x.weekday()!=4: x+=dt.timedelta(1)
    return pd.Timestamp(x)
qw=[tf(y,m) for y in range(2000,2027) for m in (3,6,9,12)]; qw=[x for x in qw if x in d.index]
for lab,names in (('our 10',ours),('related',rel)):
    ex=R[names].mean(axis=1)-S
    f5=ex[::-1].rolling(5).sum()[::-1].shift(-1)   # next 5 sessions after the Friday
    p5=ex.rolling(5).sum().shift(1)                 # 5 sessions before
    for era,(a,b) in {'00-07':('2000','2008'),'08-18':('2008','2019'),'19-26':('2019','2027')}.items():
        sel=[x for x in qw if a<=str(x.year)<b]
        base5=f5[(f5.index>=a)&(f5.index<b)].mean()
        print(f"{lab:8s} {era}: week before {p5.reindex(sel).mean()*100:+.2f}% | witching day {ex.reindex(sel).mean()*100:+.2f}% | week after {f5.reindex(sel).mean()*100:+.2f}% (normal week {base5*100:+.2f}%) n{len(sel)}")
print('t-stats (vs normal):')
for lab,names in (('our 10',ours),('related',rel)):
    ex=R[names].mean(axis=1)-S; f5=ex[::-1].rolling(5).sum()[::-1].shift(-1)
    for era,(a,b) in {'00-07':('2000','2008'),'08-18':('2008','2019'),'19-26':('2019','2027')}.items():
        sel=[x for x in qw if a<=str(x.year)<b]
        v=f5.reindex(sel).dropna(); base=f5[(f5.index>=a)&(f5.index<b)].mean(); dd=ex.reindex(sel).dropna(); bd=ex[(ex.index>=a)&(ex.index<b)].mean()
        print(f"  {lab:8s} {era}: week after t {(v.mean()-base)/(v.std()/np.sqrt(len(v))):+.1f} | witching day t {(dd.mean()-bd)/(dd.std()/np.sqrt(len(dd))):+.1f}")
