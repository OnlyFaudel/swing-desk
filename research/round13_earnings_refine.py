import pandas as pd, numpy as np, yfinance as yf
W=pd.read_pickle('/tmp/wide/wide.pkl')['Close']; spy=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']['SPY'].reindex(W.index).ffill()
X=pd.read_csv('/tmp/r12/epop_big.csv'); X['d']=pd.to_datetime(X.d); idx=W.index; s200=spy.rolling(200).mean()
def pre60(r):
    i=idx.searchsorted(r.d); c=W[r.t]
    return c.iloc[i-1]/c.iloc[max(0,i-61)]-1 if i>61 else np.nan
X['pre60']=X.apply(pre60,axis=1); X['spyup']=[bool(spy.iloc[idx.searchsorted(d)]>s200.iloc[idx.searchsorted(d)]) for d in X.d]
def show(df,label):
    out=[]
    for era,m in (('<=2018',df.yr<=2018),('2019+',df.yr>=2019)):
        y=df[m].x; out.append(f'{era} n={len(y):3d} {y.mean()*100:+.2f}% (t {y.mean()/y.std()*np.sqrt(len(y)) if len(y)>2 else 0:.1f}, beat {(y>0).mean()*100:.0f}%)')
    print(f'{label:46s} '+' | '.join(out))
show(X,'all earnings pops +8%')
show(X[X.mv<0.12],'1 pop 8-12%'); show(X[X.mv>=0.12],'1 pop 12%+')
show(X[X.pre60<=-0.20],'2 beaten down 20%+ over 60 days, then popped'); show(X[X.pre60>0.10],'2 already up 10%+ over 60 days, then popped')
show(X[X.spyup],'4 S&P above its 200-day'); show(X[~X.spyup],'4 S&P below its 200-day')
# 3 earnings drops on big stocks: need dates again; reuse yfinance earnings dates for 60 names
rows=[]
for t in [c for c in W.columns if c!='SPY'][:140]:
    try: ed=yf.Ticker(t).get_earnings_dates(limit=60)
    except Exception: continue
    if ed is None or ed.empty: continue
    c=W[t].dropna(); ix=c.index
    for d in sorted({x.date() for x in ed.index}):
        i=ix.searchsorted(pd.Timestamp(d))
        if i<2 or i+22>=len(ix): continue
        for j in (i,i+1):
            mv=c.iloc[j]/c.iloc[j-1]-1
            if mv<=-0.08:
                k=j+1; rows.append((t,ix[j].year,(c.iloc[k+20]/c.iloc[k]-1)-(spy.iloc[k+20]/spy.iloc[k]-1)-0.002)); break
Dr=pd.DataFrame(rows,columns=['t','yr','x']); show(Dr,'3 earnings DROP -8% or worse (big stocks) -> 20d')
