import pandas as pd, numpy as np, datetime as dt
d=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']; ours=['CCJ','UEC','DNN','UUUU','NXE','LEU','BWXT','CEG','VST','TLN']
R=d.pct_change(); B=R[ours].mean(axis=1); ex=B-R['SPY']
days=[]
for y in range(2000,2027):
    for m in range(1,13):
        x=dt.date(y,m,1)
        while x.weekday()!=4: x+=dt.timedelta(1)
        if x.day==1 and m in (1,):  # Jan 1 holiday; BLS moves it
            x+=dt.timedelta(7)
        days.append(pd.Timestamp(x))
days=[x for x in days if x in d.index]
def stat(sel,lab):
    for era,(a,b) in {'00-07':('2000','2008'),'08-18':('2008','2019'),'19-26':('2019','2027')}.items():
        v=sel[(sel.index>=a)&(sel.index<b)].dropna(); base=ex[(ex.index>=a)&(ex.index<b)].dropna()
        print(f"  {lab:28s} {era}: {v.mean()*100:+.2f}% vs normal {base.mean()*100:+.2f}% n{len(v)} t{(v.mean()-base.mean())/(v.std()/np.sqrt(len(v))):+.1f}")
idx=pd.DatetimeIndex(days)
stat(ex.reindex(idx),'jobs day (our 10 vs S&P)')
nxt=ex.shift(-1).reindex(idx); stat(nxt,'day after (Monday)')
pre=ex.shift(1).reindex(idx); stat(pre,'day before (Thursday)')
absr=(R['SPY'].abs()); print('  S&P abs move on jobs day %.2f%% vs normal %.2f%% (2008+)'%(absr.reindex(idx)[idx>='2008'].mean()*100, absr[absr.index>='2008'].mean()*100))
