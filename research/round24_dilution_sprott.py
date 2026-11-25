import pandas as pd, numpy as np, pickle, warnings; warnings.filterwarnings('ignore')
sh=pickle.load(open('/tmp/r24/shares.pkl','rb')); d=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']
ours=['CCJ','UEC','DNN','UUUU','NXE','LEU','BWXT','CEG','VST','TLN']
M=d.resample('ME').last(); ret=M.pct_change().shift(-1)   # next month return
spyn=ret['SPY']
rows=[]
for t,s in sh.items():
    if t not in M or t in ('SRUUF',): continue
    s=s[s>0]; s=s[(s/s.rolling(5,min_periods=1).median()).between(0.7,1.4)]   # drop bad prints
    sm=s.resample('ME').last().ffill().reindex(M.index).ffill(limit=3)
    g12=sm/sm.shift(12)-1
    for dte in M.index:
        if dte<pd.Timestamp('2017-06-30') or pd.isna(g12.get(dte)) or pd.isna(ret[t].get(dte)) or M[t].get(dte,0)<3: continue
        rows.append((dte,t,g12[dte],ret[t][dte]-spyn[dte]))
r=pd.DataFrame(rows,columns=['d','t','g','x'])
r['q']=r.groupby('d').g.transform(lambda s: pd.qcut(s.rank(method='first'),5,labels=False))
r['grp']=np.where(r.t.isin(ours),'ours','related')
print('stock-months',len(r),'stocks',r.t.nunique())
for lab,m in (('2017-21',r.d<'2022'),('2022-26',r.d>='2022')):
    g=r[m].groupby('q').x.agg(['mean','count']); print(lab,'next month vs S&P by share-growth quintile (0=least issued/buybacks, 4=most diluted):',' '.join(f"q{int(i)} {v['mean']*100:+.2f}%" for i,v in g.iterrows()))
for lab,m in (('2017-21',r.d<'2022'),('2022-26',r.d>='2022')):
    a=r[m&(r.g>0.20)].x; b=r[m&(r.g<-0.02)].x; c=r[m].x
    print(lab,'diluted 20%%+ in a year: %+.2f%% n%d | buybacks (shares down 2%%+): %+.2f%% n%d | all %+.2f%%'%(a.mean()*100,len(a),b.mean()*100,len(b),c.mean()*100))
for grp in ('ours','related'):
    for lab,m in (('2017-21',r.d<'2022'),('2022-26',r.d>='2022')):
        x=r[m&(r.grp==grp)]; print(' ',grp,lab,'top-quintile diluters %+.2f%% vs rest %+.2f%%'%(x[x.q==4].x.mean()*100,x[x.q<4].x.mean()*100))
# Sprott trust issuance
s=sh['SRUUF']; s=s[(s/s.rolling(5,min_periods=1).median()).between(0.7,1.4)]
D=d.index[d.index>='2021-08-01']; sd=s.reindex(D,method='ffill'); g20=sd/sd.shift(20)-1
miners=d[['CCJ','UEC','DNN','UUUU','NXE']].reindex(D); mb=miners.pct_change().mean(axis=1); sp=d['SPY'].reindex(D).pct_change()
f20=((1+mb).rolling(20).apply(np.prod,raw=True)-(1+sp).rolling(20).apply(np.prod,raw=True)).shift(-20)
q=g20.rolling(250,min_periods=120).quantile(0.75)
sig=(g20>q)&(g20>0.01); pick=[];last=None
for x in sig[sig].index:
    if last is None or (x-last).days>28: pick.append(x); last=x
v=f20.reindex(pick).dropna()
print('Sprott trust share count up fast (top 25%% of 20-day growth): miners next 20d vs S&P %+.2f%% n%d (all days %+.2f%%); halves %+.2f%% / %+.2f%%'%(v.mean()*100,len(v),f20.mean()*100,v[v.index<'2024'].mean()*100,v[v.index>='2024'].mean()*100))
sig2=g20<=0.001; pick=[];last=None
for x in sig2[sig2].index:
    if last is None or (x-last).days>28: pick.append(x); last=x
v2=f20.reindex(pick).dropna(); print('Sprott trust not issuing (20-day growth ~0): miners next 20d %+.2f%% n%d'%(v2.mean()*100,len(v2)))
import json
u=json.load(open('/tmp/r21/u.json')); spm=pd.Series(u['spot']); spm.index=pd.PeriodIndex(spm.index,freq='M'); spm=spm.sort_index().pct_change()
prevm=lambda x:(x.to_period('M')-1)
v=v.to_frame('r'); v['spot_prev']= [spm.get(prevm(x)) for x in v.index]; v['spot_cur']=[spm.get(x.to_period('M')) for x in v.index]
print('t-stat vs all-days mean %.1f'%((v.r.mean()-f20.mean())/(v.r.std()/np.sqrt(len(v)))))
print('picks where last month spot was up 5%%+: %d of %d; picks without that: %+.2f%% n%d'%((v.spot_prev>0.05).sum(),len(v),v[~(v.spot_prev>0.05)].r.mean()*100,(~(v.spot_prev>0.05)).sum()))
# SRUUF premium proxy: SRUUF 20d return minus spot? skip. Price momentum control: miners up 10%+ in prior 20 days
mm=(1+mb).rolling(20).apply(np.prod,raw=True)-1
v['mom']=mm.reindex(v.index)
print('picks after miners already +10%% in 20d: %d; their next 20d %+.2f%% ; others %+.2f%%'%((v.mom>0.10).sum(),v[v.mom>0.10].r.mean()*100,v[~(v.mom>0.10)].r.mean()*100))
c=(mm>0.10); pick=[];last=None
for x in c[c].index:
    if last is None or (x-last).days>28: pick.append(x); last=x
print('control: miners +10%% in 20d (any): next 20d %+.2f%% n%d'%(f20.reindex(pick).dropna().mean()*100,len(pick)))
print('SRUUF share data last date', s.index[-1].date())
