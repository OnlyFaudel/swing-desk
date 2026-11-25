import pandas as pd, numpy as np, yfinance as yf, json, time
W=pd.read_pickle('/tmp/wide/wide.pkl')['Close']; spy=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']['SPY'].reindex(W.index).ffill()
names=[t for t in W.columns if t not in ('SPY',) and t not in ('CCJ','MU','NVDA','ETN','TSM')][:140]
rows=[]; got=0
for t in names:
    try:
        ed=yf.Ticker(t).get_earnings_dates(limit=60)
    except Exception:
        continue
    if ed is None or ed.empty: continue
    got+=1; c=W[t].dropna(); idx=c.index
    for d in sorted({x.date() for x in ed.index}):
        d=pd.Timestamp(d)
        i=idx.searchsorted(d)
        if i<2 or i+22>=len(idx): continue
        # reaction day: the earnings date itself or the next session (after-close reports)
        for j in (i,i+1):
            if j>=len(idx): continue
            mv=c.iloc[j]/c.iloc[j-1]-1
            if mv>=0.08:
                k=j+1  # buy the NEXT close
                rows.append((t,str(idx[j].date()),idx[j].year,mv,(c.iloc[k+20]/c.iloc[k]-1)-(spy.iloc[k+20]/spy.iloc[k]-1)-0.002))
                break
x=pd.DataFrame(rows,columns=['t','d','yr','mv','x']).drop_duplicates(['t','d'])
print('names with earnings dates:',got,'| earnings pops +8%:',len(x),'| years',x.yr.min(),'-',x.yr.max())
for era,m in (('<=2018',x.yr<=2018),('2019+',x.yr>=2019)):
    y=x[m].x
    if len(y)>2: print(f'big stocks {era}: n={len(y)} {y.mean()*100:+.2f}% vs S&P over 20 days (t {y.mean()/y.std()*np.sqrt(len(y)):.1f}, beat {(y>0).mean()*100:.0f}%, median {y.median()*100:+.2f}%)')
x.to_csv('/tmp/r12/epop_big.csv',index=False)
