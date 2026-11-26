import pandas as pd, numpy as np, glob, os, sys, warnings; warnings.filterwarnings("ignore")
F=int(sys.argv[1]) if len(sys.argv)>1 else 5; NB=390//F
GROSS=len(sys.argv)>2 and sys.argv[2]=='gross'
path=f'/home/claude/swing-desk/data/candles{F}'
d=pd.concat([pd.read_csv(f) for f in sorted(glob.glob(path+'/*.csv.gz'))])
tt=pd.to_datetime(d.ts); d['date']=d.ts.str[:10]; d['k']=((tt.dt.hour*60+tt.dt.minute)-570)//F
d=d[(d.k>=0)&(d.k<NB)]; d=d[d.groupby(['t','date']).k.transform('size')>=NB-2]
P={f:d.pivot_table(index=['t','date'],columns='k',values=f,aggfunc='first').reindex(columns=range(NB)).sort_index() for f in ('open','high','low','close','volume','vwap')}
idx=P['close'].index; T=idx.get_level_values(0).values; D=pd.to_datetime(idx.get_level_values(1)).values
O,H,L,C,V,W=[P[k].ffill(axis=1).values for k in ('open','high','low','close','volume','vwap')]
V=np.nan_to_num(P['volume'].values); W=np.where(np.isnan(W),C,W)
CV=np.cumsum(W*V,1)/np.maximum(np.cumsum(V,1),1)
PC=pd.Series(C[:,-1],index=idx).groupby(level=0).shift().values
CH=np.maximum.accumulate(H,1); CL=np.minimum.accumulate(L,1)
cost=np.zeros(len(C)) if GROSS else 0.01/C[:,-1]+0.001
era=np.where(pd.DatetimeIndex(D).year<=2018,'2016-18','2019-26')
dv=pd.Series(C[:,-1]*V.sum(1),index=idx).groupby(level=0).transform(lambda s:s.shift().rolling(20).mean()).values
OK=~np.isnan(PC)&(T!='SPY')&~np.isnan(C).any(1)&(dv>3e6)
if GROSS: OK&=C[:,-1]>=20
R=np.arange(len(C)); bk=lambda hh,mm:((hh*60+mm)-570)//F-1   # candle whose close is at hh:mm
def first_k(cond,start,end):
    c=cond.copy(); c[:,:start]=False; c[:,end:]=False
    return np.where(c.any(1),c.argmax(1),-1)
def px(k): return np.where(k>=0,C[R,np.clip(k,0,NB-1)],np.nan)
def run(name,ek,ep,stop=None,target=None,mask=None,maxbars=None):
    m=OK&(ek>=0)&(ek<NB-1)
    if mask is not None: m&=mask
    rows=np.where(m)[0]; ex=C[rows,-1].copy()
    for n,r in enumerate(rows):
        kk=ek[r]; s=stop[r] if stop is not None else np.nan; tg=target[r] if target is not None else np.nan
        last=NB if maxbars is None else min(NB,kk+1+maxbars)
        for j in range(kk+1,last):
            if not np.isnan(s) and L[r,j]<=s: ex[n]=min(s,O[r,j]); break
            if not np.isnan(tg) and H[r,j]>=tg: ex[n]=max(tg,O[r,j]); break
        else:
            if maxbars is not None: ex[n]=C[r,last-1]
    df=pd.DataFrame({'d':D[rows],'era':era[rows],'r':ex/ep[rows]-1-cost[rows]})
    s=[]
    for E in ('2016-18','2019-26'):
        g=df[df.era==E]
        if len(g)<10: s.append(f"{E}: n {len(g)}"); continue
        pdm=g.groupby('d').r.mean(); t=pdm.mean()/(pdm.std()/np.sqrt(len(pdm)))
        s.append(f"{E}: {g.r.mean()*100:+.2f}% (n {len(g)}, t {t:+.1f}, win {(g.r>0).mean()*100:.0f}%)")
    print(f"{name}\n   "+"  |  ".join(s),flush=True)
print(f"{F}-minute candles, {sorted(set(T)-{'SPY'})}, {'NO COSTS, $20+ stocks' if GROSS else 'costs 1 tick + 0.1%'}\n")
run("0. Baseline: buy after the first candle every day, sell at close",np.zeros(len(C),int),C[:,0])
noon=bk(12,0)+1
for nb,lab in ((1,f'{F}'),(15//F,'15'),(30//F,'30')):
    orh=H[:,:nb].max(1); orl=L[:,:nb].min(1); k=first_k(C>orh[:,None],nb,noon)
    run(f"1. Opening-range breakout ({lab} min), stop at opening low, hold to close",k,px(k),stop=orl)
    run(f"1t. Same ({lab} min), but take profit at 2x the opening range height",k,px(k),stop=orl,target=orh+2*(orh-orl))
below=C<CV; rec=np.zeros_like(below); rec[:,1:]=(C[:,1:]>CV[:,1:])&below[:,:-1]
k=first_k(rec,bk(10,0)+1,bk(14,0)+1); run("2. VWAP reclaim (10-2), stop at day low so far",k,px(k),stop=np.where(k>=0,CL[R,np.clip(k,0,NB-1)],np.nan))
b=(L<=CV)&(C>CV)&(C>PC[:,None]*1.01); k=first_k(b,bk(10,0)+1,bk(14,0)+1)
run("3. VWAP bounce on an up day, stop 0.5% under VWAP",k,px(k),stop=np.where(k>=0,CV[R,np.clip(k,0,NB-1)]*0.995,np.nan))
f15=C[:,15//F-1]/O[:,0]-1; pb=(L<=CV)&(C>CV); k=first_k(pb,15//F,noon)
run("4. Opening drive (+1% in 15 min) then first pullback to VWAP that holds, stop under VWAP",np.where(f15>=0.01,k,-1),px(k),stop=np.where(k>=0,CV[R,np.clip(k,0,NB-1)]*0.995,np.nan))
avgv=np.cumsum(V,1)/np.arange(1,NB+1); prevavg=np.c_[np.full(len(V),np.nan),avgv[:,:-1]]
cr=C/O-1
burst=(cr>=0.01)&(V>=3*prevavg); k=first_k(burst,3,NB-6)
run("5. Momentum burst: a candle up 1%+ on 3x volume, buy, +1% target / -0.5% stop",k,px(k),stop=px(k)*0.995,target=px(k)*1.01)
run("5b. Momentum burst, hold 30 minutes",k,px(k),maxbars=30//F)
flush=(cr<=-0.01)&(V>=3*prevavg); k=first_k(flush,3,NB-6)
run("6. Flush: a candle down 1%+ on 3x volume, buy, target VWAP, stop -1%",k,px(k),stop=px(k)*0.99,target=np.where(k>=0,CV[R,np.clip(k,0,NB-1)],np.nan))
run("6b. Flush, hold 30 minutes",k,px(k),maxbars=30//F)
k2=bk(14,0); up=(C[:,k2]>CV[:,k2])&(C[:,k2]>PC)
run("7. 2 PM: above VWAP and up on the day, buy, sell close",np.where(up,k2,-1),C[:,k2])
