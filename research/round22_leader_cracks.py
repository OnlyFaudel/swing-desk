import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
d=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']; w=pd.read_pickle('/tmp/wide/wide.pkl')['Close']
allp=pd.concat([d,w[[c for c in w.columns if c not in d.columns]]],axis=1).sort_index()
spy=allp['SPY']
groups={'ours':['CCJ','UEC','DNN','UUUU','NXE','LEU','BWXT','CEG','VST','TLN'],
 'semis':['NVDA','AMD','AVGO','MU','TSM','QCOM','TXN','INTC','AMAT','LRCX','KLAC','ADI'],
 'banks':['JPM','BAC','WFC','C','GS','MS','USB','PNC'],'energy':['XOM','CVX','COP','SLB','EOG','OXY','HAL','MPC'],
 'megatech':['AAPL','MSFT','AMZN','GOOGL','META','NFLX','ADBE','CRM']}
print({g:len([t for t in v if t in allp]) for g,v in groups.items()})
H=20
for g,ts in groups.items():
    ts=[t for t in ts if t in allp]; p=allp[ts]; p=p[p.index>='1999']
    R=p.pct_change(); B=R.mean(axis=1); S=spy.reindex(p.index).pct_change()
    fb=(1+B).rolling(H).apply(np.prod,raw=True).shift(-H)-(1+S).rolling(H).apply(np.prod,raw=True).shift(-H)
    r60=p/p.shift(60)-1; dd=p/p.rolling(60).max()-1
    ok=r60.notna().sum(axis=1)>=4
    lead=r60[ok].idxmax(axis=1).reindex(p.index)
    ldd=pd.Series([dd.loc[i,l] if isinstance(l,str) else np.nan for i,l in lead.items()],index=p.index)
    bi=(1+B).cumprod(); bdd=bi/bi.rolling(60).max()-1
    sig=(ldd<-0.12)&(bdd>-0.05)
    row=[]
    for era,(a,b) in {'00-06':('2000','2007'),'08-18':('2008','2019'),'19-26':('2019','2027')}.items():
        days=sig[(sig.index>=a)&(sig.index<b)&sig].index; pick=[];last=None
        for x in days:
            if last is None or (x-last).days>28: pick.append(x); last=x
        v=fb.reindex(pick).dropna(); base=fb[(fb.index>=a)&(fb.index<b)].dropna()
        dif=v.mean()-base.mean(); t=dif/(v.std()/np.sqrt(len(v))) if len(v)>2 else 0
        row.append(f"{era}: {v.mean()*100:+.2f}% vs all {base.mean()*100:+.2f} n{len(v)} t{t:+.1f}")
    print(f"{g:9s}",' | '.join(row))
