import pandas as pd, numpy as np
P=pd.read_csv('/tmp/r12/epop_big.csv'); print(P.columns.tolist()[:12], len(P))
w=pd.read_pickle('/tmp/wide/wide.pkl')['Close']; spy=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']['SPY']
groups={'semis':['NVDA','AMD','AVGO','MU','TSM','QCOM','TXN','INTC','AMAT','LRCX','KLAC','ADI'],
 'banks':['JPM','BAC','WFC','C','GS','MS','USB','PNC'],'energy':['XOM','CVX','COP','SLB','EOG','OXY','HAL','MPC'],
 'megatech':['AAPL','MSFT','AMZN','GOOGL','META','NFLX','ADBE','CRM'],'retail':['WMT','COST','TGT','HD','LOW','TJX'],
 'pharma':['JNJ','PFE','MRK','ABBV','LLY','BMY','AMGN','GILD']}
G={t:g for g,ts in groups.items() for t in ts}
tcol=[c for c in P.columns if c.lower() in ('t','ticker')][0]; dcol=[c for c in P.columns if 'date' in c.lower() or c=='d'][0]
P[dcol]=pd.to_datetime(P[dcol]); rows=[]
for _,e in P.iterrows():
    t=e[tcol]
    if t not in G: continue
    i=w.index.searchsorted(e[dcol])   # pop day is the event date in this file
    if i<1 or i+6>=len(w): continue
    for p in groups[G[t]]:
        if p==t or p not in w or pd.isna(w[p].iloc[i-1]): continue
        same=w[p].iloc[i]/w[p].iloc[i-1]-1-(spy.asof(w.index[i])/spy.asof(w.index[i-1])-1)
        nxt=w[p].iloc[i+5]/w[p].iloc[i]-1-(spy.asof(w.index[i+5])/spy.asof(w.index[i])-1)-0.002
        rows.append((e[dcol],G[t],same,nxt))
r=pd.DataFrame(rows,columns=['d','g','same','next5'])
for era,(a,b) in {'2008-18':('2008','2019'),'2019-26':('2019','2027')}.items():
    x=r[(r.d>=a)&(r.d<b)]
    print(era,'all groups: peers same day %+.2f%%, next 5d %+.2f%% (t %+.1f) n%d'%(x.same.mean()*100,x.next5.mean()*100,x.next5.mean()/x.next5.std()*np.sqrt(len(x)),len(x)),
          '| big sympathy (peer +3%%+ same day): next 5d %+.2f%% n%d'%(x[x.same>0.03].next5.mean()*100,(x.same>0.03).sum()))
    print('   by group:',' '.join(f"{g} {y.next5.mean()*100:+.2f}%({len(y)})" for g,y in x.groupby('g')))
