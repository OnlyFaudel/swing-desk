import pandas as pd, numpy as np, json
D=pd.read_pickle('/tmp/sz/daily_max.pkl')
O,H,Lo,C=D['Open'],D['High'],D['Low'],D['Close']
cfg=json.load(open('/home/claude/swing-desk/config.json'))
uni=[t for t in C.columns if t not in('SPY','^VIX','SGOV','SSO','QQQ','^GSPC')]
spy=C['SPY'] if 'SPY' in C else None
C=C[C.index>='2005-01-01']; O,H,Lo=O.loc[C.index],H.loc[C.index],Lo.loc[C.index]; spy=spy.loc[C.index]
sr=spy.pct_change(); s200=spy.rolling(200).mean()
hold=6; cost=0.002
rows=[]
for t in uni:
    c=C[t]; 
    if c.notna().sum()<300: continue
    r=c.pct_change(); hi20=H[t].rolling(20).max(); c50=c.rolling(50).mean()
    sig=(sr<=-0.02)&(r<=-0.03)&(c<=hi20*0.85)&(c>=3)
    idx=np.where(sig.fillna(False).values)[0]; last=-99
    for i in idx:
        if i-last<hold or i+hold>=len(c): continue
        last=i; e=c.iloc[i]
        if not np.isfinite(e): continue
        o=O[t].iloc[i+1:i+hold+1].values; h=H[t].iloc[i+1:i+hold+1].values; cl=c.iloc[i+1:i+hold+1].values
        if not np.all(np.isfinite(cl)): continue
        res={}
        # live: sell at close if close>=+10%, else day-6 close
        x=cl[-1]
        for k in range(hold):
            if cl[k]>=e*1.10: x=cl[k];break
        res['close_only_10']=x/e-1
        for tp in (0.05,0.07,0.10,0.15):
            x=cl[-1]; tgt=e*(1+tp)
            for k in range(hold):
                if o[k]>=tgt: x=o[k];break
                if h[k]>=tgt: x=tgt;break
            res[f'limit_{int(tp*100)}']=x/e-1
        sp=spy.iloc[i+hold]/spy.iloc[i]-1
        rows.append(dict(t=t,d=c.index[i],yr=c.index[i].year,below200=bool(spy.iloc[i]<s200.iloc[i]),stock_below50=bool(e<c50.iloc[i]),spy=sp,**res))
R=pd.DataFrame(rows)
cols=[k for k in R.columns if k.startswith(('close','limit'))]
for k in cols: R[k]=(R[k]-cost)*100
R['spy']*=100
def show(df,label):
    if len(df)==0: return
    print(f"{label:28s} n={len(df):4d} | "+" | ".join(f"{k} {df[k].mean():+.2f}% (worst5% {df[k].quantile(.05):+.1f})" for k in cols)+f" | S&P {df.spy.mean():+.2f}")
for era,df in (('2008-18',R[(R.yr>=2008)&(R.yr<=2018)]),('2019-26',R[R.yr>=2019])):
    show(df,era)
    show(df[df.below200],era+' S&P<200d')
    show(df[~df.below200],era+' S&P>200d')
    show(df[df.below200&df.stock_below50],era+' S&P<200d & stock<50d')
# t-stat of limit_10 minus close_only_10 in downtrend
for era,df in (('2008-18',R[(R.yr>=2008)&(R.yr<=2018)&R.below200]),('2019-26',R[(R.yr>=2019)&R.below200])):
    for k in ('limit_5','limit_7','limit_10'):
        d=df[k]-df.close_only_10; print(era,'down-trend',k,'minus live: %+.2f%% t=%.1f'%(d.mean(), d.mean()/d.std()*np.sqrt(len(d)) if d.std()>0 else 0))
print('touched +10% intraday but not at a close:', ((R.limit_10>R.close_only_10+0.01)|(R.limit_10<R.close_only_10-0.01)).sum())
R.to_pickle('/tmp/tp/R.pkl')
