import pandas as pd, numpy as np, yfinance as yf, warnings; warnings.filterwarnings('ignore')
I=pd.read_pickle('/tmp/r41/intraday.pkl'); I['date']=pd.to_datetime(I.date); I=I.sort_values(['t','date'])
I['n935']=I.groupby('t').px935.shift(-1)
a=I[I.ah_px.notna()].copy(); a['ah']=a.ah_px/a.close-1; a['vs']=a.ah_vol/a.vol
dn=a[(a.ah<=-0.03)&(a.vs>=0.01)&a.n935.notna()].copy(); dn['r']=dn.n935/(dn.ah_px*1.003)-1-0.01
ed=set()
for t in sorted(I.t.unique()):
    try:
        e=yf.Ticker(t).get_earnings_dates(limit=60)
        if e is not None: ed|={(t,pd.Timestamp(d.date())) for d in e.index}|{(t,pd.Timestamp(d.date())-pd.Timedelta(days=1)) for d in e.index}
    except Exception: pass
dn['earn']=[(r.t,r.date) in ed for r in dn.itertuples()]; x=dn[~dn.earn]
print('earnings-night skips:',dn.earn.sum(),'| trades left',len(x))
g=x.groupby('t').r.agg(['count','mean',lambda s:(s>0).mean()]); g.columns=['n','avg','up']; print((g.assign(avg=g.avg*100,up=g.up*100)).round(2).to_string())
for per,m in (('2016-2023',x.date.dt.year<=2023),('2024-2026',x.date.dt.year>=2024)):
    s=x[m].r; print(f"all stocks {per}: n {len(s)} {s.mean()*100:+.2f}% (t {s.mean()/s.std()*np.sqrt(len(s)):.1f}, up {(s>0).mean()*100:.0f}%)")
new=x[x.t.isin(['OKLO','CEG','NXE','VST','TLN'])]
print('stocks whose history was incomplete before tonight (CEG, NXE, VST, TLN) + new OKLO: n %d %+.2f%% up %.0f%%'%(len(new),new.r.mean()*100,(new.r>0).mean()*100))
o=x[x.t=='OKLO'].r; print('OKLO only (never in the original test): n %d %+.2f%% up %.0f%%'%(len(o),o.mean()*100,(o>0).mean()*100))
