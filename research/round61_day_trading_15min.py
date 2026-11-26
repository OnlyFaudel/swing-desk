import pandas as pd, numpy as np, warnings; warnings.filterwarnings("ignore")
o=pd.read_pickle('/tmp/r61/c15.pkl'); O,H,L,C,V,W=[o[k] for k in ('open','high','low','close','volume','vwap')]
idx=C.index; T=idx.get_level_values(0).values; D=pd.to_datetime(idx.get_level_values(1)).values
O,H,L,C,V,W=[x.values for x in (O,H,L,C,V,W)]
W=np.where(np.isnan(W),C,W)
CV=np.cumsum(W*V,1)/np.maximum(np.cumsum(V,1),1)            # running VWAP, known at each candle's close
PC=pd.Series(C[:,-1],index=idx).groupby(level=0).shift().values  # previous day's last close
CH=np.maximum.accumulate(H,1); CL=np.minimum.accumulate(L,1)
cost=0.01/C[:,-1]+0.001
era=np.where(pd.DatetimeIndex(D).year<=2018,'2016-18','2019-26')
dv=pd.Series(C[:,-1]*V.sum(1),index=idx).groupby(level=0).transform(lambda s:s.shift().rolling(20).mean()).values
OK=(dv>3e6)&~np.isnan(PC)&(T!='SPY')
# SPY context per date: above its running VWAP at each candle, and day return
spy=pd.Series(range(len(idx)),index=idx).loc['SPY'] if 'SPY' in set(T) else None
spyd={}
if spy is not None:
    for dte,i in spy.items(): spyd[pd.Timestamp(dte)]=i
SPYI=np.array([spyd.get(pd.Timestamp(d),-1) for d in D])
def spy_ok(rows,k):
    s=SPYI[rows]; good=s>=0
    out=np.zeros(len(rows),bool); out[good]=C[s[good],k[good]]>CV[s[good],k[good]]
    return out,good
def run(name,entry_k,entry_px,stop=None,target=None,mask=None,spyf=False):
    """entry_k: candle index whose CLOSE triggers entry (-1 = no trade). Exit: stop/target checked on later candles, else day close."""
    m=OK&(entry_k>=0)&(entry_k<25)
    if mask is not None: m&=mask
    rows=np.where(m)[0]; k=entry_k[rows]
    if spyf:
        ok,good=spy_ok(rows,k); rows,k=rows[ok&good],k[ok&good]
    e=entry_px[rows]; ex=C[rows,-1].copy()
    for n,(r,kk) in enumerate(zip(rows,k)):
        s=stop[r] if stop is not None else np.nan; tg=target[r] if target is not None else np.nan
        for j in range(kk+1,26):
            if not np.isnan(s) and L[r,j]<=s: ex[n]=min(s,O[r,j]); break
            if not np.isnan(tg) and H[r,j]>=tg: ex[n]=max(tg,O[r,j]); break
    ret=ex/e-1-cost[rows]
    df=pd.DataFrame({'d':D[rows],'era':era[rows],'r':ret,'t':T[rows]})
    s=[]
    for E in ('2016-18','2019-26'):
        g=df[df.era==E]
        if len(g)<10: s.append(f"{E}: n {len(g)}"); continue
        pdm=g.groupby('d').r.mean(); t=pdm.mean()/(pdm.std()/np.sqrt(len(pdm)))
        s.append(f"{E}: {g.r.mean()*100:+.2f}%/trade (n {len(g)}, t {t:+.1f}, win {(g.r>0).mean()*100:.0f}%)")
    print(f"{name}{' [SPY above its VWAP]' if spyf else ''}\n   "+"\n   ".join(s),flush=True)
    return df
def first_k(cond,start,end):
    c=cond.copy(); c[:,:start]=False; c[:,end:]=False
    k=np.where(c.any(1),c.argmax(1),-1); return k
R=np.arange(len(C))
def px_at(k): return np.where(k>=0,C[R,np.clip(k,0,25)],np.nan)
print("Real 15-minute candles, 13 stocks, 2016-2026. Long only, entry at a candle's close, out by 4 PM. Costs: 1 tick + 0.1%.\n")
base=np.full(len(C),1); run("0. Baseline: buy at 9:45 every day, sell at close",base,C[:,0])
# 1-2 opening range breakouts
for n_or,lab in ((1,'15'),(2,'30')):
    orh=H[:,:n_or].max(1); orl=L[:,:n_or].min(1)
    k=first_k(C>orh[:,None],n_or,10)  # break by 12:00
    for spyf in (False,True):
        run(f"1. Opening-range breakout ({lab} min): first close above the opening high before noon, stop at the opening low",k,px_at(k),stop=orl,spyf=spyf)
# 3 VWAP reclaim: was below VWAP, closes back above, 10:00-14:00
below=C<CV; reclaim=np.zeros_like(below); reclaim[:,1:]=(C[:,1:]>CV[:,1:])&below[:,:-1]
k=first_k(reclaim,2,18)
run("3. VWAP reclaim: closes back above VWAP (10:00-2:00), stop at the day's low so far",k,px_at(k),stop=np.where(k>=0,CL[R,np.clip(k,0,25)],np.nan))
run("3b. VWAP reclaim, only on days the stock is up vs yesterday",k,px_at(k),stop=np.where(k>=0,CL[R,np.clip(k,0,25)],np.nan),mask=px_at(k)>PC)
run("3c. VWAP reclaim",k,px_at(k),stop=np.where(k>=0,CL[R,np.clip(k,0,25)],np.nan),spyf=True)
# 4 VWAP bounce in an up day
bounce=(L<=CV)&(C>CV)&(C>PC[:,None]*1.01)
k=first_k(bounce,2,18); run("4. VWAP bounce: up 1%+ on the day, dips to VWAP and closes above, stop 0.5% under VWAP",k,px_at(k),stop=np.where(k>=0,CV[R,np.clip(k,0,25)]*0.995,np.nan))
run("4b. VWAP bounce",k,px_at(k),stop=np.where(k>=0,CV[R,np.clip(k,0,25)]*0.995,np.nan),spyf=True)
# 5 first-candle momentum
fr=C[:,0]/O[:,0]-1
run("5. First candle up 1%+ (9:30-9:45), buy 9:45, sell close",np.where(fr>=0.01,0,-1),C[:,0])
run("5b. First candle down 1%+, buy 9:45, sell close",np.where(fr<=-0.01,0,-1),C[:,0])
# 6 gap-down fill confirmed by opening range break
gap=O[:,0]/PC-1; orh=H[:,:2].max(1); orl=L[:,:2].min(1)
k=first_k(C>orh[:,None],2,10)
run("6. Gap down 2%+, then breaks the 30-min opening high: target yesterday's close, stop opening low",np.where(gap<=-0.02,k,-1),px_at(k),stop=orl,target=PC)
# 7 afternoon trend
k14=np.full(len(C),17)  # candle 17 closes at 14:00
up14=(C[:,17]>CV[:,17])&(C[:,17]>PC)
run("7. 2 PM trend: above VWAP and up on the day at 2:00, buy, sell close",np.where(up14,17,-1),C[:,17])
run("7b. 2 PM trend",np.where(up14,17,-1),C[:,17],spyf=True)
dn14=(C[:,17]<CV[:,17])&(C[:,17]<PC*0.98)
run("7c. 2 PM weakness: below VWAP and down 2%+, buy, sell close",np.where(dn14,17,-1),C[:,17])
# 8 new high of day after 1 PM
nh=np.zeros_like(below); nh[:,1:]=C[:,1:]>CH[:,:-1]
k=first_k(nh,14,24); run("8. Breaks to a new high of the day after 1 PM, buy, stop at VWAP",k,px_at(k),stop=np.where(k>=0,CV[R,np.clip(k,0,25)],np.nan))
