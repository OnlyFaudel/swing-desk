import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
d=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']; spy=d['SPY']
ours=['CCJ','UEC','DNN','UUUU','NXE','LEU','BWXT','CEG','VST','TLN']
rel=[t for t in d.columns if t not in ours+['SPY']]
def run(ts,H=20,k=2,ddmin=-0.15,label=''):
    p=d[ts]; p=p[p.index>='1999']; R=p.pct_change()
    B=(1+R.mean(axis=1)).cumprod(); dd=B/B.rolling(60).max()-1; above=B>B.rolling(20).mean()
    trig=(dd.shift(1).rolling(10).min()<=ddmin)&above&~above.shift(1).fillna(False)
    rows=[];last=None
    for x in trig[trig].index:
        if last is not None and (x-last).days<40: continue
        last=x; i=p.index.get_loc(x)
        if i+H>=len(p): continue
        win=p.iloc[max(0,i-60):i+1]; sdd=(win.iloc[-1]/win.max()-1).dropna()
        sdd=sdd[p.iloc[i][sdd.index]>3]
        if len(sdd)<4: continue
        weak=sdd.nsmallest(k).index
        fr=p.iloc[i+H]/p.iloc[i]-1-(spy.asof(p.index[i+H])/spy.asof(p.index[i])-1)
        rows.append((x,fr[weak].mean()-0.002,fr.dropna().mean()-0.002,list(weak)))
    r=pd.DataFrame(rows,columns=['d','worst','group','names'])
    out=[]
    for era,(a,b) in {'00-07':('2000','2008'),'08-18':('2008','2019'),'19-26':('2019','2027')}.items():
        x=r[(r.d>=a)&(r.d<b)]
        if len(x)>1:
            t=(x.worst).mean()/x.worst.std()*np.sqrt(len(x)); te=(x.worst-x.group).mean()/(x.worst-x.group).std()*np.sqrt(len(x))
            out.append(f"{era}: worst{k} {x.worst.mean()*100:+.2f}% (t {t:+.1f}; vs group t {te:+.1f}) group {x.group.mean()*100:+.2f}% up {(x.worst>0).mean()*100:.0f}% n{len(x)}")
    print(f"{label:28s}",' || '.join(out)); return r
r=run(ours,label='ours worst2 20d')
run(ours,H=10,label='ours worst2 10d'); run(ours,k=3,label='ours worst3 20d'); run(ours,ddmin=-0.20,label='ours worst2 20d, dd 20%')
run(rel,label='related (78) worst2 20d'); run(rel,k=5,label='related worst5 20d')
print(r.tail(8).to_string())
