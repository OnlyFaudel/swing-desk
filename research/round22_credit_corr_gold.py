import pandas as pd, numpy as np, yfinance as yf, warnings; warnings.filterwarnings('ignore')
d=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']
ours=['CCJ','UEC','DNN','UUUU','NXE','LEU','BWXT','CEG','VST','TLN']
rel=[t for t in d.columns if t not in ours+['SPY']]
x=yf.download(['VWEHX','VFIIX','GC=F','SI=F','GLD','^GSPC'],start='1995-01-01',progress=False,auto_adjust=True)['Close']
spy=d['SPY'].dropna(); idx=spy.index[spy.index>='1998-01-01']
R=d.reindex(idx).pct_change()
B=R[ours].mean(axis=1); Brel=R[rel].mean(axis=1); S=R['SPY']
x=x.reindex(idx).ffill()
def fwd(s,h): return (1+s).rolling(h).apply(np.prod,raw=True).shift(-h)-1
def study(name,sig,target,h=20,gap=None):
    gap=gap or h; out={}
    f=fwd(target,h); fs=fwd(S,h); base=(f-fs)
    for era,(a,b) in {'00-06':('2000','2007'),'08-18':('2008','2019'),'19-26':('2019','2027')}.items():
        s=sig[(sig.index>=a)&(sig.index<b)].fillna(False); days=s[s].index; pick=[];last=None
        for dd in days:
            if last is None or (dd-last).days>gap*1.4: pick.append(dd); last=dd
        v=base.reindex(pick).dropna(); allv=base[(base.index>=a)&(base.index<b)].dropna()
        out[era]=f"{v.mean()*100:+.2f}% n{len(v)} (all {allv.mean()*100:+.2f})"
    print(f"{name:46s}", ' | '.join(f"{k}: {v}" for k,v in out.items()), flush=True)
hy=x['VWEHX']; 
# 1-2 credit
study('ours: HY fund under its 100d avg', hy<hy.rolling(100).mean(), B)
study('ours: HY fund 2%+ off its 1-yr high', hy<hy.rolling(250).max()*0.98, B)
study('ours: HY fund 10-day drop 2%+ (credit scare)', hy/hy.shift(10)<0.98, B, 10)
study('S&P itself: HY under 100d (vs own avg)', hy<hy.rolling(100).mean(), S*0+S-S.rolling(1).mean()*0, 20)
# 3 dispersion
corr=R[ours].rolling(20).corr()
avgc=corr.groupby(level=0).apply(lambda m: (m.values[np.triu_indices_from(m.values,1)]).astype(float)).apply(lambda a: np.nanmean(a) if len(a) else np.nan)
q=avgc.rolling(500,min_periods=250)
study('ours: basket correlation in bottom 10%', avgc<q.quantile(0.1), B)
study('ours: basket correlation in top 10%', avgc>q.quantile(0.9), B)
# 4 leader breaks first
p=d.reindex(idx)[ours]; r60=p/p.shift(60)-1; dd=p/p.rolling(60).max()-1
lead=r60.idxmax(axis=1)
ldd=pd.Series([dd.loc[i,l] if isinstance(l,str) else np.nan for i,l in lead.items()],index=idx)
bdd=(1+B).cumprod(); bdd=bdd/bdd.rolling(60).max()-1
study('ours: 60d leader down 12%+ while basket within 5%', (ldd<-0.12)&(bdd>-0.05), B)
# 5 gold
g=x['GC=F']; 
study('ours: gold up 5%+ in 20 days', g/g.shift(20)>1.05, B)
study('miners only: gold up 5%+ in 20 days', g/g.shift(20)>1.05, R[['CCJ','UEC','DNN','UUUU','NXE']].mean(axis=1))
gs=g/x['SI=F']
study('ours: gold/silver ratio top 10% (fear)', gs>gs.rolling(500,min_periods=250).quantile(0.9), B)
study('ours: gold/silver ratio bottom 10% (risk-on)', gs<gs.rolling(500,min_periods=250).quantile(0.1), B)
