import pandas as pd, numpy as np, json, warnings; warnings.filterwarnings("ignore")
N=pd.read_pickle('/tmp/sz/daily_max.pkl'); C,L,V=N['Close'],N['Low'],N['Volume']
Z=pd.read_pickle('sso.pkl'); X=pd.read_pickle('/tmp/sz/cross.pkl')['Close']
NUC=["CCJ","NXE","UEC","DNN","UUUU","LEU","BWXT","CEG","VST","TLN"]
REL=[t for t in json.load(open('/home/claude/swing-desk/config.json'))['panic_rebound']['related_universe'] if t in C and t not in NUC]
U=NUC+REL
idx=C.loc["2007-06-01":].index
C=C.reindex(idx); L=L.reindex(idx); V=V.reindex(idx)
spy=C['SPY']; sma=spy.rolling(200).mean(); above=(spy>sma)
sso=Z['SSO'].reindex(idx).ffill(); tb=(Z['^IRX'].reindex(idx).ffill()/100/252).fillna(0)
vix=X['^VIX'].reindex(idx).ffill()
R=C.pct_change(); r5=C.pct_change(5); dv=(C*V).rolling(20).mean(); ok=(C>3)&(dv>5e6)
HI20=C.rolling(20).max()
def run(start, end=None, parking=True, rules=("panic","sharp","comeback"), cost=0.002):
    days=idx[(idx>=start)&((idx<=end) if end else True)]
    I={d:i for i,d in enumerate(idx)}
    cash=1000.0; pos=[]; curve=[]; ntr={k:0 for k in rules}
    for d in days:
        i=I[d]
        # parked cash earns SSO (above 200d) or T-bills (below), decided at yesterday's close
        if parking and i>0:
            pr=(sso.iloc[i]/sso.iloc[i-1]-1) if above.iloc[i-1] else tb.iloc[i]
            if np.isnan(pr): pr=0
            cash*=1+pr
        keep=[]
        for p in pos:
            px=C.iat[i,p['j']]
            if np.isnan(px): keep.append(p); continue
            done=False
            if p['k']=="panic": done = px>=p['e']*1.10 or i-p['i']>=6
            if p['k']=="sharp": done = px>=p['e']*1.10 or i-p['i']>=10
            if p['k']=="comeback":
                if L.iat[i,p['j']]<=p['e']*0.85: px=p['e']*0.85; done=True
                done = done or i-p['i']>=20
            if done: cash+=p['q']*px*(1-cost/2)
            else: keep.append(p)
        pos=keep
        val=cash+sum(p['q']*(C.iat[i,p['j']] if not np.isnan(C.iat[i,p['j']]) else p['e']) for p in pos)
        curve.append(val)
        held={p['j'] for p in pos}
        def buy(j,frac,k):
            nonlocal cash
            amt=min(val*frac,cash)
            if amt<5: return
            px=C.iat[i,j]*(1+cost/2); pos.append(dict(j=j,q=amt/px,e=C.iat[i,j],i=i,k=k)); cash-=amt; held.add(j); ntr[k]+=1
        if "panic" in rules and spy.iloc[i]/spy.iloc[i-1]-1<=-0.02:
            hits=[(R.iat[i,j],j) for j,t in enumerate(C.columns) if t in NUC and ok.iat[i,j] and R.iat[i,j]<=-0.03 and C.iat[i,j]/HI20.iat[i,j]-1<=-0.15]
            fill=[(C.iat[i,j]/HI20.iat[i,j]-1,j) for j,t in enumerate(C.columns) if t in REL and ok.iat[i,j] and R.iat[i,j]<=-0.03 and C.iat[i,j]/HI20.iat[i,j]-1<=-0.15]
            picks=[j for _,j in sorted(hits)]+[j for _,j in sorted(fill)]
            npan=sum(1 for p in pos if p['k']=="panic")
            for j in picks[:max(0,3-npan)]:
                if j in held: continue
                vx=vix.iloc[i]; s=1 if (vx<25 or vx>=40) else -1; s+=1 if R.iat[i,j]<=-0.08 else (-1 if R.iat[i,j]>-0.05 else 0)
                step=[10,15,25,40,50][max(0,min(4,2+s))] if above.iloc[i] else 10
                buy(j,step/100,"panic")
        if "sharp" in rules:
            ns=sum(1 for p in pos if p['k']=="sharp")
            for j in sorted([j for j,t in enumerate(C.columns) if t in U and ok.iat[i,j] and r5.iat[i,j]<=-0.15 and j not in held], key=lambda j:R.iat[i,j])[:max(0,3-ns)]:
                buy(j,0.15 if r5.iat[i,j]<=-0.20 else 0.10,"sharp")
        if "comeback" in rules and not above.iloc[i] and i>0:
            nc=sum(1 for p in pos if p['k']=="comeback")
            cands=[j for j,t in enumerate(C.columns) if t in U and ok.iat[i,j] and j not in held and L.iat[i,j]/C.iat[i-1,j]-1<=-0.06 and C.iat[i,j]>C.iat[i-1,j]]
            for j in cands[:max(0,3-nc)]: buy(j,0.10,"comeback")
    e=pd.Series(curve,index=days); y=(days[-1]-days[0]).days/365.25
    yr=e.resample("YE").last(); yr=pd.concat([pd.Series([1000.0],index=[days[0]]),yr]).pct_change().dropna()*100
    return e,(e.iloc[-1]/1000)**(1/y)-1,(e/e.cummax()-1).min(),ntr,yr
for lab,kw in (("S&P buy-and-hold",None),("parking only (SSO/T-bills)",dict(rules=())),("full stack",dict()),("full stack, plain S&P parking",dict(parking=False))):
    if kw is None:
        e=spy.loc["2008-01-01":]; y=(e.index[-1]-e.index[0]).days/365.25
        print(f"{lab:32s} {((e.iloc[-1]/e.iloc[0])**(1/y)-1)*100:5.1f}%/yr worst {((e/e.cummax()-1).min())*100:6.1f}%"); continue
    if not kw.get("parking",True):
        sso0,ab0=globals()['sso'],globals()['above']; globals()['sso']=spy; globals()['above']=pd.Series(True,index=idx)
        e,cg,dd,n,yr=run("2008-01-01",**{k:v for k,v in kw.items() if k!="parking"}); globals()['sso'],globals()['above']=sso0,ab0
    else:
        e,cg,dd,n,yr=run("2008-01-01",**kw)
    print(f"{lab:32s} {cg*100:5.1f}%/yr worst {dd*100:6.1f}% | $1,000 -> ${e.iloc[-1]:,.0f} | trades {n}")
    if lab=="full stack": print("   by year:", {d.year:round(v,1) for d,v in yr.items()})
