import pandas as pd, numpy as np
d=pd.read_pickle('trades.pkl'); P=pd.read_pickle('px.pkl').ffill(limit=5); idx=P.index; spy=P['SPY']
B=d[d.buy&d.ticker.isin(P.columns)&(d.tx>='2014-01-01')&(d.tx<='2026-10-01')].copy()
rows=[]
for r in B.itertuples():
    i=idx.searchsorted(r.tx)
    if i<260 or i+14>=len(idx): continue
    p=P[r.ticker]; a=p.iloc[i]
    if not np.isfinite(a): continue
    pre20=(a/p.iloc[i-20]-1)-(spy.iloc[i]/spy.iloc[i-20]-1)
    hi=p.iloc[i-252:i].max(); vol=p.pct_change().iloc[i-20:i].std()*np.sqrt(252)
    spy200=spy.iloc[i]>spy.iloc[i-200:i].mean()
    edge=(p.iloc[i+10]/a-1)-(spy.iloc[i+10]/spy.iloc[i]-1)   # THEIR edge: from their trade day, 10 sessions
    rows.append(dict(who=r.who,yr=r.tx.year,pre20=pre20,off_high=a/hi-1,vol=vol,spy_up=spy200,edge=edge))
X=pd.DataFrame(rows).dropna()
print('all buys n',len(X),'their 10-day edge %+.2f%%'%(X.edge.mean()*100))
X['setup']=pd.cut(X.pre20,[-9,-.15,-.05,.05,.15,9],labels=['after big drop (<-15%)','after dip (-15..-5%)','flat','after rise (5..15%)','after big rise (>15%)'])
X['near']=pd.cut(X.off_high,[-1,-.4,-.2,-.05,0.01],labels=['>40% off high','20-40% off','5-20% off','at highs'])
X['regime']=np.where(X.spy_up,'S&P above 200d','S&P below 200d')
for col in ('setup','near','regime'):
    g=X.groupby(col,observed=True).edge.agg(['count','mean','std'])
    g['t']=g['mean']/g['std']*np.sqrt(g['count']); g['mean']=(g['mean']*100).round(2)
    print(g[['count','mean','t']].round(2).to_string()); print()
# who has a real early edge? members with 15+ buys, their 10-day edge
m=X.groupby('who').edge.agg(['count','mean','std']); m=m[m['count']>=15]; m['t']=m['mean']/m['std']*np.sqrt(m['count'])
print('members with t>2 on their own 10-day edge:', (m.t>2).sum(),'of',len(m), '(by luck we would expect about', round(len(m)*0.023,1),')')
print(m.sort_values('t',ascending=False).head(6).assign(mean=lambda x:(x['mean']*100).round(2)).round(2).to_string())
