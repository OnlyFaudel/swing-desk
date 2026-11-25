import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
d=pd.read_pickle('/tmp/sz/daily_max.pkl'); w=pd.read_pickle('/tmp/wide/wide.pkl')
spy=d['Close']['SPY']
def trades(df,names):
    out=[]
    for t in names:
        C=df['Close'][t].dropna()
        if len(C)<300: continue
        O,H=df['Open'][t].reindex(C.index),df['High'][t].reindex(C.index)
        V=df['Volume'][t].reindex(C.index); ok=(C>3)&((C*V).rolling(20).mean()>5e6)
        sig=(C/C.shift(5)<=0.85)&ok; i=60
        idx=np.where(sig.values)[0]; last=-99
        for i in idx:
            if i-last<10 or i+11>=len(C): continue
            last=i; e=C.iloc[i]; tp=e*1.10
            # A: live: sell at a close >= +10%, else close of day 10
            a=None; b=None
            for k in range(1,11):
                if a is None and C.iloc[i+k]>=tp: a=(C.iloc[i+k],k)
                if b is None and (O.iloc[i+k]>=tp or H.iloc[i+k]>=tp): b=(max(O.iloc[i+k],tp),k)   # resting limit at +10%
            a=a or (C.iloc[i+10],10); b=b or (C.iloc[i+10],10)
            c=(C.iloc[i+10],10)  # no target
            # D: 15% target at a close
            dd=next(((C.iloc[i+k],k) for k in range(1,11) if C.iloc[i+k]>=e*1.15),(C.iloc[i+10],10))
            ee=next(((C.iloc[i+k],k) for k in range(1,11) if C.iloc[i+k]>=e*1.06),(C.iloc[i+10],10))
            sp=lambda k: spy.asof(C.index[i+k])/spy.asof(C.index[i])-1
            row=dict(d=C.index[i])
            for nm,(px,k) in (('live +10% at a close',a),('resting limit +10%',b),('no target, 10 sessions',c),('+15% at a close',dd),('+6% at a close',ee)):
                row[nm]=px/e-1-0.002-sp(k); row[nm+'_k']=k
            out.append(row)
    return pd.DataFrame(out)
nuc=[t for t in d['Close'].columns if t!='SPY']
for lab,df,names in (('ours',d,nuc),('wide',w,[t for t in w['Close'].columns if t not in nuc and t!='SPY'])):
    r=trades(df,names)
    for era,(a,b) in {'08-18':('2008','2019'),'19-26':('2019','2027')}.items():
        x=r[(r.d>=a)&(r.d<b)]
        print(lab,era,'n',len(x),' | '.join(f"{c}: {x[c].mean()*100:+.2f}% ({x[c+'_k'].mean():.1f}d)" for c in ['live +10% at a close','resting limit +10%','no target, 10 sessions','+15% at a close','+6% at a close']))
