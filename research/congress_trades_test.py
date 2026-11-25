import pandas as pd, numpy as np
d=pd.read_pickle('trades.pkl'); P=pd.read_pickle('px.pkl').ffill(limit=5); idx=P.index; spy=P['SPY']
d=d[(d.tx>='2014-01-01')&(d.tx<='2026-11-20')&d.ticker.isin(P.columns)&(d.buy|d.sell)].copy()
# when could WE act: House = day after the disclosure date (drop impossible lags); Senate has no filing date -> assume 30 days (median-ish legal window)
d['act']=np.where(d.chamber=='House', d.disc, d.tx+pd.Timedelta(days=30))
d=d[(d.chamber=='Senate')|((d.lag>=0)&(d.lag<=120))]
d['act']=pd.to_datetime(d.act)
cost=0.002
def fwd(t, start, n):
    i=idx.searchsorted(start)+1  # next trading day close
    if i+n>=len(idx): return np.nan, np.nan
    a,b=P[t].iloc[i],P[t].iloc[i+n]; s=spy.iloc[i+n]/spy.iloc[i]-1
    if not(np.isfinite(a) and np.isfinite(b)) or a<=0: return np.nan,np.nan
    return b/a-1, s
rows=[]
for r in d.itertuples():
    rec={'t':r.ticker,'who':r.who,'buy':r.buy,'yr':r.act.year,'amt':r.amount,'ch':r.chamber,'tx':r.tx,'act':r.act}
    for n in (20,60):
        x,s=fwd(r.ticker,r.act,n); rec[f'r{n}']=x; rec[f'x{n}']=x-s if x==x else np.nan
    x,s=fwd(r.ticker,r.tx,0) if False else (np.nan,np.nan)
    i0,i1=idx.searchsorted(r.tx),idx.searchsorted(r.act)
    if i1>i0 and i1<len(idx) and np.isfinite(P[r.ticker].iloc[i0]) and np.isfinite(P[r.ticker].iloc[i1]):
        rec['missed']=P[r.ticker].iloc[i1]/P[r.ticker].iloc[i0]-1-(spy.iloc[i1]/spy.iloc[i0]-1)
    rows.append(rec)
R=pd.DataFrame(rows); R.to_pickle('R.pkl')
def show(df,label):
    for era,m in (('2014-18',df.yr<=2018),('2019-26',df.yr>=2019)):
        x=df[m]
        if len(x)<15: print(f'{label:44s} {era} n={len(x)} too few'); continue
        out=[]
        for n in (20,60):
            e=x[f'x{n}'].dropna()-(cost if n else 0)
            out.append(f'{n}d vs S&P {e.mean()*100:+.2f}% (t {e.mean()/e.std()*np.sqrt(len(e)):.1f}, beat {(e>0).mean()*100:.0f}%)')
        ms=x.missed.dropna()
        print(f'{label:44s} {era} n={len(x):5d} | '+' | '.join(out)+f' | move we MISSED before public {ms.mean()*100:+.2f}%')
B,S=R[R.buy],R[~R.buy]
show(B,'Copy every disclosed BUY')
show(S,'After every disclosed SALE (should fall?)')
big=B[B.amt.str.contains(r'\$50,001|\$100,001|\$250,001|\$500,001|\$1,000,001|\$5,000,001',regex=True,na=False)]; show(big,'Copy big buys ($50k+)')
show(B[B.who.str.contains('Pelosi',na=False)],'Copy Pelosi buys')
# clusters: 3+ different members buy the same stock within 30 days (act date of the 3rd)
B2=B.sort_values('act'); cl=[]
for t,g in B2.groupby('t'):
    g=g.drop_duplicates('who')
    for i in range(2,len(g)):
        if (g.act.iloc[i]-g.act.iloc[i-2]).days<=30: cl.append(g.index[i])
show(R.loc[sorted(set(cl))],'Cluster: 3+ members buy same stock in 30d')
# contrarian check: does a buy predict the stock does WORSE than the S&P?
NUC=['CCJ','NXE','UEC','DNN','UUUU','LEU','BWXT','CEG','VST','TLN','OKLO','SMR','NNE','URG','GEV']
n=R[R.t.isin(NUC)]; print('nuclear names: buys',int(n.buy.sum()),'sells',int((~n.buy).sum()),'| buys 60d vs S&P %+.1f%%, sells 60d vs S&P %+.1f%%'%(n[n.buy].x60.mean()*100, n[~n.buy].x60.mean()*100))
