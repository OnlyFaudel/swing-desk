import pandas as pd, numpy as np, yfinance as yf, warnings; warnings.filterwarnings('ignore')
ev=[('2015-08-21',164.77,120.0),('2016-05-24',100.0,164.77),('2017-05-23',76.53,100.0),('2018-05-23',140.0,76.53),
    ('2021-06-02',50.0,140.0),('2022-06-21',34.13,50.0),('2023-02-27',28.92,34.13),('2024-07-30',269.92,28.92),
    ('2025-07-22',329.17,269.92),('2025-12-17',333.44,329.17)]
tk=['VST','NRG','CEG','TLN','PEG','EXC','XLU','SPY']
px=yf.download(tk,start='2015-01-01',progress=False,auto_adjust=True)['Close']
rows=[]
for d,p,prev in ev:
    d=pd.Timestamp(d); i=px.index.searchsorted(d)   # i = results day (results usually posted after the close or during the day)
    for t in ['VST','NRG','CEG','TLN','PEG','EXC']:
        s=px[t]
        if pd.isna(s.iloc[i-1]): continue
        def rel(a,b): return (s.iloc[b]/s.iloc[a]-1)-(px.XLU.iloc[b]/px.XLU.iloc[a]-1)
        rows.append(dict(date=d.date(),up=p>prev,chg=p/prev-1,t=t,day0_2=rel(i-1,i+1),next5=rel(i+1,i+6),next20=rel(i+1,i+21),pre10=rel(i-11,i-1)))
r=pd.DataFrame(rows)
pd.set_option('display.width',200)
print((r.groupby(['date','up']).agg(chg=('chg','first'),n=('t','size'),reaction=('day0_2','mean'),next5=('next5','mean'),next20=('next20','mean'),run_in=('pre10','mean'))*[1,100,1,100,100,100,100]).round(1) if False else r.groupby(['date','up'])[['chg','day0_2','next5','next20','pre10']].mean().mul(100).round(1))
for u in (True,False):
    g=r[r.up==u]; print('price UP' if u else 'price DOWN', 'auctions', g.date.nunique(), 'reaction 2d %+.1f%%'%(g.day0_2.mean()*100),
          'run-in 10d %+.1f%%'%(g.pre10.mean()*100),'next5 %+.1f%%'%(g.next5.mean()*100),'next20 %+.1f%%'%(g.next20.mean()*100))
