import pandas as pd, numpy as np
D=pd.read_pickle('/tmp/sz/daily_max.pkl'); D=D[D.index>='2007-01-01']; C=D['Close']; spy=C['SPY']; cost=0.002
X=pd.read_pickle('/tmp/sz/cross.pkl')['Close'].reindex(C.index).ffill(); nv=X['NVDA'].pct_change()
def ev(names,n=5,gap=5):
    out=[]; last=-99
    for i in np.where((nv>=0.06).values)[0]:
        if i+n>=len(C) or i-last<gap: continue
        xs=[(C[t].iloc[i+n]/C[t].iloc[i]-1)-(spy.iloc[i+n]/spy.iloc[i]-1)-cost for t in names if t in C and np.isfinite(C[t].iloc[i]) and np.isfinite(C[t].iloc[i+n]) and C[t].iloc[i]>=3]
        if xs: out.append((C.index[i].year,np.mean(xs))); last=i
    return pd.DataFrame(out,columns=['yr','x'])
for lab,names in (('live: CEG, VST, TLN',['CEG','VST','TLN']),('grid/electrical: ETN, PWR, HUBB, POWL, VRT, GEV',['ETN','PWR','HUBB','POWL','VRT','GEV']),('utilities: NRG, PEG, ETR',['NRG','PEG','ETR'])):
    for n in (5,10):
        E=ev(names,n)
        print(f'T {lab:44s} {n:2d}d '+' | '.join(f'{e} days={len(y):3d} {y.x.mean()*100:+.2f}% (t {y.x.mean()/y.x.std()*np.sqrt(len(y)):.1f})' for e,y in (('08-18',E[E.yr<=2018]),('19-26',E[E.yr>=2019])) if len(y)>2))
