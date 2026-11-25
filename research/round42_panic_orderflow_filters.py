import pandas as pd, numpy as np
I=pd.read_pickle('/tmp/r41/intraday.pkl'); I['date']=pd.to_datetime(I.date)
C=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']; spy=C['SPY']; S=spy.pct_change(); R=C.pct_change(); hi20=C.rolling(20).max()
rows=[]
for r in I.itertuples():
    t,d=r.t,r.date
    if t not in C or d not in C.index: continue
    i=C.index.get_loc(d)
    if i<21 or i+7>=len(C): continue
    if not(S.iloc[i]<=-0.02 and R[t].iloc[i]<=-0.03 and C[t].iloc[i]<=hi20[t].iloc[i]*0.85): continue
    c=C[t].values; ex=next((k for k in range(1,7) if c[i+k]>=c[i]*1.10),6)
    ret=c[i+ex]/c[i]-1-(spy.iloc[i+ex]/spy.iloc[i]-1)-0.002
    off_low=r.px1530/r.low-1 if r.low_min is not None and r.low_min<=360 else 0.0   # bounce off the day's low already made before 15:30
    rows.append((d,t,ret,r.press15,r.press30,off_low,r.low_min,r.vol15/r.vol if r.vol else np.nan))
x=pd.DataFrame(rows,columns=['d','t','ret','press15','press30','off_low','low_min','vol15share'])
print('panic trades with minute data:',len(x), x.d.min().date(), x.d.max().date())
def split(lab,m):
    for per,pm in (('2016-20',x.d<'2021'),('2021-26',x.d>='2021')):
        a=x[pm&m].ret; b=x[pm&~m].ret
        print(f"  {lab:40s} {per}: {a.mean()*100:+.2f}% (n {len(a)}) vs rest {b.mean()*100:+.2f}% (n {len(b)})")
split('selling hard in the first 15 min (press15<-0.2)',x.press15<-0.2)
split('buying in the first 30 min (press30>0)',x.press30>0)
split('already 3%+ off the low by 15:30',x.off_low>=0.03)
split('low printed in the last hour (low_min>330)',x.low_min>330)
split('heavy first-15-min volume (>15% of day)',x.vol15share>0.15)
print('day-clustered (average per panic day first):')
def cl(lab,m):
    for per,pm in (('2016-20',x.d<'2021'),('2021-26',x.d>='2021')):
        a=x[pm&m].groupby('d').ret.mean(); b=x[pm&~m].groupby('d').ret.mean()
        se=np.sqrt(a.var()/max(len(a),1)+b.var()/len(b)) if len(a)>1 else np.nan
        print(f"  {lab:34s} {per}: {a.mean()*100:+.2f}% ({len(a)} days) vs {b.mean()*100:+.2f}% ({len(b)} days) t {(a.mean()-b.mean())/se:+.1f}")
cl('heavy first-15-min volume',x.vol15share>0.15); cl('already 3%+ off the low by 15:30',x.off_low>=0.03)
cl('buying in the first 30 min',x.press30>0); cl('low printed in the last hour',x.low_min>330)
