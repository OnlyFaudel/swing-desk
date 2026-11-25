import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
def run(path,exclude=None,label=''):
    d=pd.read_pickle(path); C=d['Close']; V=d['Volume']
    spy=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']['SPY'].reindex(C.index).ffill(); S=spy.pct_change()
    names=[t for t in C.columns if t!='SPY' and (exclude is None or t not in exclude)]
    R=C.pct_change(); hi20=C.rolling(20).max(); r5=C/C.shift(5)-1; dv=(C*V).rolling(20).mean()
    rows=[]
    for t in names:
        c=C[t].values; last=-99
        for i in range(30,len(c)-35):
            if np.isnan(c[i]) or c[i]<3 or not(dv[t].iloc[i]>5e6) or i-last<10: continue
            is_p=S.iloc[i]<=-0.02 and R[t].iloc[i]<=-0.03 and c[i]<=hi20[t].iloc[i]*0.85
            is_s=r5[t].iloc[i]<=-0.15
            if not(is_p or is_s): continue
            last=i; N=6 if is_p else 10
            ex=next((k for k in range(1,N+1) if c[i+k]>=c[i]*1.10),None)
            if ex is None: continue     # only winners that hit +10%
            j=i+ex; xp=c[j]
            # re-entry: first close 5%+ below the exit price within 10 sessions; hold 10 sessions or +10% at a close
            k=next((m for m in range(1,11) if c[j+m]<=xp*0.95),None)
            hold_after=c[j+10]/c[j]-1-(spy.iloc[j+10]/spy.iloc[j]-1)   # what simply staying in after +10% would have done
            if k is None: rows.append((C.index[i],np.nan,hold_after)); continue
            e=j+k; ex2=next((m for m in range(1,11) if c[e+m]>=c[e]*1.10),10)
            rows.append((C.index[i],c[e+ex2]/c[e]-1-(spy.iloc[e+ex2]/spy.iloc[e]-1)-0.002,hold_after))
    r=pd.DataFrame(rows,columns=['d','reentry','stay'])
    for era,(a,b) in {'00-07':('2000','2008'),'08-18':('2008','2019'),'19-26':('2019','2027')}.items():
        x=r[(r.d>=a)&(r.d<b)]; y=x.reentry.dropna()
        if len(x)<10: continue
        print(f"{label:6s} {era}: winners {len(x)} | pullback re-entries {len(y)}: {y.mean()*100:+.2f}% (t {y.mean()/y.std()*np.sqrt(len(y)):+.1f}, up {(y>0).mean()*100:.0f}%) | staying in 10 more days after the +10% exit {x.stay.mean()*100:+.2f}%")
d0=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close'].columns
run('/tmp/sz/daily_max.pkl',label='ours'); run('/tmp/wide/wide.pkl',exclude=set(d0),label='wide')
