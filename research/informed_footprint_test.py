import pandas as pd, numpy as np
D=pd.read_pickle('/tmp/sz/daily_max.pkl'); D=D[D.index>='2008-01-01']
C,H,L,V=D['Close'],D['High'],D['Low'],D['Volume']; spy=C['SPY']; cost=0.002
uni=[t for t in C.columns if t not in('SPY','URA','URNM')]
rows=[]; pre=[]
for t in uni:
    c,v,h,l=C[t],V[t],H[t],L[t]
    if c.notna().sum()<400: continue
    r=c.pct_change(); av=v.rolling(20).mean().shift(1); rv=v/av; dv=(c*v).rolling(20).mean()
    rng=((c-l)/(h-l)).where(h>l)
    ok=(c>=3)&(dv>=5e6)
    sigs={
     'A volume 3x, price calm (|move|<2%)': (rv>=3)&(r.abs()<0.02),
     'B volume 3x, closed near the high, small gain (0-3%)': (rv>=3)&(r>0)&(r<0.03)&(rng>=0.7),
     'C quiet accumulation: 3 days volume 2x, price within 3%': (rv>=2)&(rv.shift(1)>=2)&(rv.shift(2)>=2)&((c/c.shift(3)-1).abs()<0.03),
     'D strength on a red market day: stock +2%, S&P -1%': (r>=0.02)&(spy.pct_change()<=-0.01)&(rv>=1.5),
    }
    for name,s in sigs.items():
        idx=np.where((s&ok).fillna(False).values)[0]; last=-99
        for i in idx:
            if i-last<10 or i+20>=len(c): continue
            last=i
            for n in (5,20):
                pass
            rows.append(dict(sig=name,t=t,yr=c.index[i].year,
                x5=(c.iloc[i+5]/c.iloc[i]-1)-(spy.iloc[i+5]/spy.iloc[i]-1)-cost,
                x20=(c.iloc[i+20]/c.iloc[i]-1)-(spy.iloc[i+20]/spy.iloc[i]-1)-cost,
                big=(c.iloc[i+1:i+21].max()/c.iloc[i]-1)>=0.20))
    # base rate: how often does any random day see a +20% run in the next 20 days?
    fwdmax=pd.Series([c.iloc[i+1:i+21].max()/c.iloc[i]-1 if i+21<len(c) else np.nan for i in range(len(c))],index=c.index)
    pre.append(((fwdmax>=0.20)&ok).sum()/ok.sum())
R=pd.DataFrame(rows)
print('base rate: chance of a +20%% run within 20 days on any day = %.1f%%'%(np.nanmean(pre)*100))
for name,g in R.groupby('sig'):
    for era,m in (('2008-18',g.yr<=2018),('2019-26',g.yr>=2019)):
        x=g[m]
        print(f'{name[:58]:58s} {era} n={len(x):4d} | 5d vs S&P {x.x5.mean()*100:+.2f}% (t {x.x5.mean()/x.x5.std()*np.sqrt(len(x)):.1f}) | 20d {x.x20.mean()*100:+.2f}% (t {x.x20.mean()/x.x20.std()*np.sqrt(len(x)):.1f}) | +20% run after {x.big.mean()*100:.0f}%')
R.to_pickle('/tmp/congwork/foot.pkl')
