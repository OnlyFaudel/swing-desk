import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
d=pd.read_pickle('/tmp/sz/daily_max.pkl'); w=pd.read_pickle('/tmp/wide/wide.pkl')
def trades(df,names):
    out=[]
    for t in names:
        C=df['Close'][t].dropna()
        if len(C)<400: continue
        H=df['High'][t].reindex(C.index).values; L=df['Low'][t].reindex(C.index).values; V=df['Volume'][t].reindex(C.index)
        c=C.values; ma=C.rolling(200).mean().values; lo20=pd.Series(L,index=C.index).shift(1).rolling(20).min().values
        dv=(C*V).rolling(20).mean().values; last=-99
        for i in range(220,len(c)-16):
            if i-last<5 or c[i]<3 or not(dv[i]>5e6): continue
            sup=lo20[i]
            if not(sup>0 and sup<c[i]<=sup*1.02 and L[i]>=sup*0.995): continue   # tested support today and held it
            stop=sup*0.98; risk=c[i]-stop
            if risk<=0: continue
            tgt=c[i]+1.5*risk; R=None
            for k in range(1,16):
                if L[i+k]<=stop: R=(min(stop,c[i+k-1] if False else stop)-c[i])/risk; break
                if H[i+k]>=tgt: R=1.5; break
            if R is None: R=(c[i+15]-c[i])/risk
            R-=0.002*c[i]/risk
            out.append((C.index[i],t,R,c[i]>ma[i])); last=i
    return pd.DataFrame(out,columns=['d','t','R','above200'])
nuc=[t for t in d['Close'].columns if t!='SPY']
for lab,df,names in (('ours (88)',d,nuc),('wide (140)',w,[t for t in w['Close'].columns if t not in nuc and t!='SPY'])):
    r=trades(df,names)
    for era,(a,b) in {'2008-18':('2008','2019'),'2019-26':('2019','2027')}.items():
        x=r[(r.d>=a)&(r.d<b)]
        A=x[x.above200].R; B=x[~x.above200].R
        se=np.sqrt(A.var()/len(A)+B.var()/len(B))
        print(f"{lab:11s} {era}: above 200-day R {A.mean():+.3f} (n {len(A)}, win {(A>0).mean()*100:.0f}%) | below R {B.mean():+.3f} (n {len(B)}, win {(B>0).mean()*100:.0f}%) | diff t {(A.mean()-B.mean())/se:+.1f}")
