import pandas as pd, numpy as np, yfinance as yf
G=yf.download(['^VVIX','^SKEW','^VIX9D','^VIX','SPY'],start='2007-01-01',auto_adjust=True,progress=False)['Close'].ffill()
D=pd.read_pickle('/tmp/sz/daily_max.pkl'); C=D['Close'].reindex(G.index).ffill(); spy=C['SPY']; cost=0.002
NUC=["CCJ","NXE","UEC","DNN","UUUU","LEU","BWXT","CEG","VST","TLN"]
bk=(1+C[NUC].pct_change().mean(axis=1).fillna(0)).cumprod()
print('data from:', {c:str(G[c].first_valid_index())[:10] for c in G.columns})
def ev(sig,label,n=10,gap=10):
    out=[]; last=-99
    for i in np.where(sig.fillna(False).values)[0]:
        if i+n>=len(G) or i-last<gap: continue
        last=i; out.append((G.index[i].year,(bk.iloc[i+n]/bk.iloc[i]-1)-(spy.iloc[i+n]/spy.iloc[i]-1)-cost,(spy.iloc[i+n]/spy.iloc[i]-1)))
    x=pd.DataFrame(out,columns=['yr','x','s'])
    s=' | '.join(f'{e} n={len(y):3d} basket vs S&P {y.x.mean()*100:+.2f}% (t {y.x.mean()/y.x.std()*np.sqrt(len(y)) if len(y)>2 else 0:.1f}), S&P itself {y.s.mean()*100:+.2f}%' for e,y in (('08-18',x[x.yr<=2018]),('19-26',x[x.yr>=2019])))
    print(f'{label:44s} {s}')
vv=G['^VVIX']; sk=G['^SKEW']; v9=G['^VIX9D']; v=G['^VIX']
ev(vv>=vv.rolling(250).quantile(0.95),'VVIX in its top 5% of the past year')
ev((vv>=vv.rolling(250).quantile(0.95))&(vv<vv.shift(1)),'VVIX top 5% and falling')
ev(sk>=sk.rolling(250).quantile(0.95),'SKEW (crash pricing) top 5%')
ev(sk<=sk.rolling(250).quantile(0.05),'SKEW bottom 5% (complacent)')
ev((v9/v>=1.10),'VIX9D 10%+ above VIX (short-term panic)')
ev((v9/v>=1.10)&(v9/v).shift(1).ge(1.10)&((v9/v)<(v9/v).shift(1)),'short-term panic easing')
# month of year and day of week, basket vs S&P
r=(bk.pct_change()-spy.pct_change()).dropna()
m=r.groupby([r.index.year<=2018, r.index.month]).sum()/r.groupby([r.index.year<=2018, r.index.month]).apply(lambda s:len(set(s.index.year)))
print('month: basket vs S&P per month (avg), 2008-18 | 2019-26')
for mo in range(1,13): print(f'  {mo:2d}: {m.get((True,mo),np.nan)*100:+6.2f}% | {m.get((False,mo),np.nan)*100:+6.2f}%')
dw=r.groupby([r.index.year<=2018, r.index.dayofweek]).agg(['mean','std','count'])
print('weekday: basket vs S&P per day, 2008-18 | 2019-26')
for d in range(5):
    a=dw.loc[(True,d)]; b=dw.loc[(False,d)]
    print(f'  {"MTWTF"[d]}: {a["mean"]*100:+.3f}% (t {a["mean"]/a["std"]*np.sqrt(a["count"]):.1f}) | {b["mean"]*100:+.3f}% (t {b["mean"]/b["std"]*np.sqrt(b["count"]):.1f})')
