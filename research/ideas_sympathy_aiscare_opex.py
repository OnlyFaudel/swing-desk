import pandas as pd, numpy as np, json
D=pd.read_pickle('/tmp/sz/daily_max.pkl'); D=D[D.index>='2008-01-01']
C,V=D['Close'],D['Volume']; spy=C['SPY']; R=C.pct_change(); sr=spy.pct_change(); cost=0.002
X=pd.read_pickle('/tmp/sz/cross.pkl')['Close'].reindex(C.index).ffill(); nv=X['NVDA'].pct_change()
dv=(C*V).rolling(20).mean(); ok=(C>=3)&(dv>=3e6)
G={'miners':['CCJ','NXE','UEC','DNN','UUUU','URG','EU','ENCUF'],'fuel and tech':['LEU','BWXT'],'power':['CEG','VST','TLN','NRG','PEG','ETR'],
   'small reactors':['OKLO','SMR','NNE']}
def fwd(t,i,n):
    if i+n>=len(C): return np.nan
    return (C[t].iloc[i+n]/C[t].iloc[i]-1)-(spy.iloc[i+n]/spy.iloc[i]-1)-cost
def rep(rows,label):
    x=pd.DataFrame(rows)
    if x.empty: print(label,'no trades'); return
    for era,m in (('2008-18',x.yr<=2018),('2019-26',x.yr>=2019)):
        y=x[m]
        if len(y)<8: print(f'{label:52s} {era} n={len(y)} too few'); continue
        print(f'{label:52s} {era} n={len(y):4d} | '+' | '.join(f'{n}d vs S&P {y[f"x{n}"].mean()*100:+.2f}% (t {y[f"x{n}"].mean()/y[f"x{n}"].std()*np.sqrt(y[f"x{n}"].notna().sum()):.1f})' for n in (5,10)))
# 1. sympathy: a group member falls 10%+ on its own (S&P > -1%); buy peers that fell 3-8% the same day
rows=[]
for g,mem in G.items():
    mem=[t for t in mem if t in C]
    for i in range(1,len(C)-11):
        if not (sr.iloc[i]>-0.01): continue
        lead=[t for t in mem if ok[t].iloc[i] and R[t].iloc[i]<=-0.10]
        if not lead: continue
        for p in mem:
            if p in lead or not ok[p].iloc[i]: continue
            if -0.08<=R[p].iloc[i]<=-0.03:
                rows.append(dict(yr=C.index[i].year,x5=fwd(p,i,5),x10=fwd(p,i,10)))
rep(rows,'1 Sympathy: peer fell 3-8% when a group mate crashed 10%+')
rows=[]
for g,mem in G.items():
    mem=[t for t in mem if t in C]
    for i in range(1,len(C)-11):
        if not (sr.iloc[i]>-0.01): continue
        for t in mem:
            if ok[t].iloc[i] and R[t].iloc[i]<=-0.10: rows.append(dict(yr=C.index[i].year,x5=fwd(t,i,5),x10=fwd(t,i,10)))
rep(rows,'  (the crashed stock itself, for comparison)')
# 2. AI scare day: NVDA -6%+, buy power names (and the lineup) at the close
for grp,names in (('power',['CEG','VST','TLN','NRG']),('lineup',['CCJ','NXE','UEC','DNN','UUUU','LEU','BWXT','CEG','VST','TLN'])):
    rows=[]
    for i in np.where((nv<=-0.06).values)[0]:
        if i+11>=len(C): continue
        for t in names:
            if t in C and ok[t].iloc[i]: rows.append(dict(yr=C.index[i].year,x5=fwd(t,i,5),x10=fwd(t,i,10)))
    rep(rows,f'2 AI scare day (NVIDIA -6%+): buy {grp}')
# 3. options-expiration week: basket in the week ending the 3rd Friday vs the week after
L=['CCJ','NXE','UEC','DNN','UUUU','LEU','BWXT','CEG','VST','TLN']
bk=R[[t for t in L if t in R]].mean(axis=1)-sr
d=pd.Series(C.index,index=C.index); fri=d[(d.dt.weekday==4)&(d.dt.day>=15)&(d.dt.day<=21)]
wk=bk.rolling(5).sum()
ox=wk.reindex(fri.index).dropna(); after=wk.shift(-5).reindex(fri.index).dropna()
for lab,s in (('opex week',ox),('week after opex',after),('all weeks',wk.iloc[::5].dropna())):
    for era,m in (('2008-18',s.index.year<=2018),('2019-26',s.index.year>=2019)):
        y=s[m]; print(f'3 {lab:20s} {era} n={len(y):4d} basket vs S&P {y.mean()*100:+.2f}%/week (t {y.mean()/y.std()*np.sqrt(len(y)):.1f})')
