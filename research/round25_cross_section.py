import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
d=pd.read_pickle('/tmp/sz/daily_max.pkl'); w=pd.read_pickle('/tmp/wide/wide.pkl')
def prep(df):
    C=df['Close']; V=df['Volume']; return C,V
Ca,Va=prep(d); Cb,Vb=prep(w)
spy=Ca['SPY']
def run(C,V,names,label):
    C=C[names]; V=V[names].reindex(C.index)
    R=C.pct_change(); S=spy.reindex(C.index).pct_change()
    me=C.resample('ME').last().index
    dv=(C*V).rolling(20).mean()
    res={}
    for i,m in enumerate(me[13:-1]):
        j=me[13+i+1]
        win=R[(R.index>me[13+i-1])&(R.index<=m)]       # last month's daily returns
        if len(win)<15: continue
        last=C[C.index<=m].iloc[-1]; ok=(last>3)&(dv[dv.index<=m].iloc[-1]>5e6)&win.notna().sum().gt(14)
        nxt=C[C.index<=j].iloc[-1]/last-1-(spy[spy.index<=j].iloc[-1]/spy[spy.index<=m].iloc[-1]-1)-0.002
        sw=S.reindex(win.index)
        beta=win.apply(lambda x: x.cov(sw)/sw.var())
        ivol=(win.sub(sw,axis=0).sub(0)).std()   # simple market-adjusted vol
        h252=C[C.index<=m].tail(252).max()
        f={'MAX (biggest 1-day gain last month)':win.max(),'idiosyncratic vol':ivol,'1-month return (reversal)':win.add(1).prod()-1,
           'closeness to 52-week high':last/h252}
        for k,v in f.items():
            v=v[ok].dropna(); n=nxt.reindex(v.index).dropna(); v=v.reindex(n.index)
            if len(v)<15: continue
            q=pd.qcut(v.rank(method='first'),5,labels=False)
            res.setdefault(k,[]).append((m,n[q==0].mean(),n[q==4].mean(),n.mean()))
    for k,rows in res.items():
        r=pd.DataFrame(rows,columns=['m','lo','hi','all']).set_index('m')
        out=[]
        for era,(a,b) in {'00-07':('2000','2008'),'08-18':('2008','2019'),'19-26':('2019','2027')}.items():
            x=r[(r.index>=a)&(r.index<b)]
            if len(x)<12: continue
            t=lambda s: s.mean()/s.std()*np.sqrt(len(s))
            out.append(f"{era}: low {x.lo.mean()*100:+.2f} high {x.hi.mean()*100:+.2f} all {x['all'].mean()*100:+.2f} (low-all t {t(x.lo-x['all']):+.1f}, high-all t {t(x.hi-x['all']):+.1f})")
        print(f"{label} {k:38s}",' | '.join(out),flush=True)
nuc=[t for t in Ca.columns if t!='SPY']
run(Ca,Va,nuc,'ours')
run(Cb,Vb,[t for t in Cb.columns if t not in nuc and t!='SPY'],'wide')
