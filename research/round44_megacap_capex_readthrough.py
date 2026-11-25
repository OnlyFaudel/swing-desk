import pandas as pd, numpy as np, yfinance as yf, warnings; warnings.filterwarnings('ignore')
C=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']; spy=C['SPY']
power=[t for t in ['CEG','VST','TLN','NRG','ETN','VRT','GEV','PWR'] if t in C]; print('power names',power)
rows=[]
for m in ['MSFT','GOOGL','AMZN','META']:
    e=yf.Ticker(m).get_earnings_dates(limit=80)
    if e is None: continue
    for d in e.index:
        d=pd.Timestamp(d.date())
        if d>C.index[-1]: continue
        i=C.index.searchsorted(d+pd.Timedelta(days=1))   # megacaps report after the close: reaction is the next session
        if i+6>=len(C) or i<1: continue
        mv=None
        R=C[power].iloc[i]/C[power].iloc[i-1]-1-(spy.iloc[i]/spy.iloc[i-1]-1)
        f5=C[power].iloc[i+5]/C[power].iloc[i]-1-(spy.iloc[i+5]/spy.iloc[i]-1)-0.002
        rows.append((C.index[i],m,R.mean(),f5.mean()))
r=pd.DataFrame(rows,columns=['d','m','react','next5']).dropna().drop_duplicates('d')
for per,(a,b) in {'2012-22':('2012','2023'),'2023-26':('2023','2027')}.items():
    x=r[(r.d>=a)&(r.d<b)]
    print(f"{per}: megacap earnings reactions n {len(x)} | power names reaction day {x.react.mean()*100:+.2f}% | next 5d {x.next5.mean()*100:+.2f}% (t {x.next5.mean()/x.next5.std()*np.sqrt(len(x)):+.1f}) | after a +2% power reaction: next 5d {x[x.react>0.02].next5.mean()*100:+.2f}% n{(x.react>0.02).sum()}")
