import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
d=pd.read_pickle('/tmp/sz/daily_max.pkl'); C=d['Close']; Lo=d['Low']; V=d['Volume']; spy=C['SPY']; S=spy.pct_change()
names=[t for t in C.columns if t!='SPY']; R=C.pct_change(); hi20=C.rolling(20).max(); r5=C/C.shift(5)-1; dv=(C*V).rolling(20).mean()
low120=Lo.shift(1).rolling(120).min()
rows=[]
for t in names:
    c=C[t].values; last=-99
    for i in range(130,len(c)-12):
        if np.isnan(c[i]) or c[i]<3 or not(dv[t].iloc[i]>5e6) or i-last<10: continue
        is_p=S.iloc[i]<=-0.02 and R[t].iloc[i]<=-0.03 and c[i]<=hi20[t].iloc[i]*0.85
        is_s=r5[t].iloc[i]<=-0.15
        if not(is_p or is_s): continue
        last=i; N=6 if is_p else 10
        sp=lambda k: spy.iloc[i+k]/spy.iloc[i]-1
        ex=next((k for k in range(1,N+1) if c[i+k]>=c[i]*1.10),N); live=c[i+ex]/c[i]-1-sp(ex)-0.002
        def early(day,th):
            if ex>day and c[i+day]/c[i]-1<th: return c[i+day]/c[i]-1-sp(day)-0.002
            return live
        near=c[i]<=low120[t].iloc[i]*1.03
        rows.append((C.index[i],'panic' if is_p else 'sharp',live,early(3,0.0),early(3,-0.05),early(2,-0.03),near,c[i+3]/c[i]-1))
r=pd.DataFrame(rows,columns=['d','kind','live','x3_below0','x3_below_m5','x2_below_m3','near_support','d3'])
for era,(a,b) in {'2000-07':('2000','2008'),'2008-18':('2008','2019'),'2019-26':('2019','2027')}.items():
    for k in ('panic','sharp'):
        x=r[(r.d>=a)&(r.d<b)&(r.kind==k)]
        if len(x)<20: continue
        print(f"{era} {k:5s} n{len(x):4d} live {x.live.mean()*100:+.2f}% | exit day3 if below cost {x.x3_below0.mean()*100:+.2f}% | day3 if -5% {x.x3_below_m5.mean()*100:+.2f}% | day2 if -3% {x.x2_below_m3.mean()*100:+.2f}% | worst5% live {x.live.quantile(.05)*100:.1f} vs {x.x3_below_m5.quantile(.05)*100:.1f} | near 120-day low {x[x.near_support].live.mean()*100:+.2f}% (n{x.near_support.sum()}) vs not {x[~x.near_support].live.mean()*100:+.2f}%")
