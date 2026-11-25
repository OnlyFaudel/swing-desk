import pandas as pd, numpy as np, json, warnings; warnings.filterwarnings("ignore")
N=pd.read_pickle('/tmp/sz/daily_max.pkl'); C,L,V=N['Close'],N['Low'],N['Volume']
Z=pd.read_pickle('sso.pkl'); X=pd.read_pickle('/tmp/sz/cross.pkl')['Close']
NUC=["CCJ","NXE","UEC","DNN","UUUU","LEU","BWXT","CEG","VST","TLN"]
REL=[t for t in json.load(open('/home/claude/swing-desk/config.json'))['panic_rebound']['related_universe'] if t in C and t not in NUC]
U=NUC+REL
WW=pd.read_pickle('/tmp/wide/wide.pkl')
WIDE=[t for t in sorted(set(WW.columns.get_level_values(1))) if t not in C.columns]
C=pd.concat([C,WW['Close'][WIDE]],axis=1); L=pd.concat([L,WW['Low'][WIDE]],axis=1); V=pd.concat([V,WW['Volume'][WIDE]],axis=1)
import os
TIER2=[t for t in WIDE if t not in os.environ.get('DROP','').split(',')] if os.environ.get('WIDE')=='1' else []
SLOTS=int(os.environ.get('SLOTS','3')); PW=os.environ.get('PANICWIDE')=='1'; CW=os.environ.get('CBWIDE')=='1'; VS=float(os.environ.get('VIXSHARP','1')); F3=os.environ.get('FAST3')=='1'; RANK=os.environ.get('RANK','today'); PARK=os.environ.get('PARK','SSO'); PADD=os.environ.get('PANICADD')=='1'
idx=C.loc["2007-06-01":].index
C=C.reindex(idx); L=L.reindex(idx); V=V.reindex(idx)
spy=C['SPY']; sma=spy.rolling(200).mean(); above=(spy>sma)
sso=Z['SSO'].reindex(idx).ffill()
if os.environ.get('PARK','SSO')=='QLD':
    QQ=pd.read_pickle('/tmp/wide/qld.pkl').reindex(idx).ffill(); sso=QQ['QLD']; pabove=(QQ['QQQ']>QQ['QQQ'].rolling(200).mean())
else:
    pabove=above
tb=(Z['^IRX'].reindex(idx).ffill()/100/252).fillna(0)
vix=X['^VIX'].reindex(idx).ffill(); nvda=X['NVDA'].reindex(idx).ffill()
R=C.pct_change(); r5=C.pct_change(5); dv=(C*V).rolling(20).mean(); ok=(C>3)&(dv>5e6)
HI20=C.rolling(20).max()
def run(start, end=None, parking=True, rules=("panic","sharp","comeback"), cost=0.002, brake=None, brake_mult=0.5):
    days=idx[(idx>=start)&((idx<=end) if end else True)]
    I={d:i for i,d in enumerate(idx)}
    cash=1000.0; pos=[]; curve=[]; ntr={k:0 for k in rules}; state={}
    for d in days:
        i=I[d]
        # parked cash earns SSO (above 200d) or T-bills (below), decided at yesterday's close
        if parking and i>0:
            pr=(sso.iloc[i]/sso.iloc[i-1]-1) if pabove.iloc[i-1] else tb.iloc[i]
            if np.isnan(pr): pr=0
            cash*=1+pr
        keep=[]
        for p in pos:
            px=C.iat[i,p['j']]
            if np.isnan(px): keep.append(p); continue
            done=False
            if p['k']=="panic" and PADD and not p.get('added') and px<=p['e0']*0.90 and i-p['i']<6:
                amt=min(p['q']*p['e0'],cash)
                if amt>=5:
                    q2=amt/(px*(1+cost/2)); p['e']=(p['q']*p['e']+q2*px)/(p['q']+q2); p['q']+=q2; cash-=amt; p['added']=True
            if p['k']=="panic": done = px>=p['e']*1.10 or i-p['i']>=6
            if p['k']=="sharp": done = px>=p['e']*1.10 or i-p['i']>=10
            if p['k'] in ("fear","ai","yearend","tg"): done = i>=p['x']
            if p['k']=="comeback":
                if L.iat[i,p['j']]<=p['e']*0.85: px=p['e']*0.85; done=True
                done = done or i-p['i']>=20
            if done: cash+=p['q']*px*(1-cost/2)
            else: keep.append(p)
        pos=keep
        val=cash+sum(p['q']*(C.iat[i,p['j']] if not np.isnan(C.iat[i,p['j']]) else p['e']) for p in pos)
        curve.append(val); state['peak']=max(state.get('peak',val),val)
        held={p['j'] for p in pos}
        def buy(j,frac,k,x=None):
            nonlocal cash
            amt=min(val*frac*(brake_mult if (brake and val<state['peak']*(1-brake)) else 1),cash)
            if amt<5: return
            px=C.iat[i,j]*(1+cost/2); pos.append(dict(j=j,q=amt/px,e=C.iat[i,j],e0=C.iat[i,j],i=i,k=k,x=x)); cash-=amt; held.add(j); ntr[k]+=1
        cols=list(C.columns)
        if "fear" in rules and i>2 and vix.iloc[i]>30 and vix.iloc[i]<vix.iloc[i-1]<vix.iloc[i-2] and i-state.get('lastfear',-99)>=20:
            state['lastfear']=i; js=[cols.index(t) for t in NUC if ok.iat[i,cols.index(t)] and cols.index(t) not in held]
            for j in js: buy(j,0.20/len(js),"fear",i+20)
        if "ai" in rules and i>0 and nvda.iloc[i]/nvda.iloc[i-1]-1>=0.06:
            js=[cols.index(t) for t in ("CEG","VST","TLN") if t in cols and ok.iat[i,cols.index(t)] and cols.index(t) not in held]
            for j in js: buy(j,0.15/len(js),"ai",i+5)
        if "yearend" in rules and d.month==12 and d.day>=18 and state.get('ye')!=d.year:
            state['ye']=d.year; y0=idx[(idx.year==d.year)][0]; i0=I[y0]
            ytd=[(C.iat[i,cols.index(t)]/C.iat[i0,cols.index(t)]-1,cols.index(t)) for t in NUC if ok.iat[i,cols.index(t)] and not np.isnan(C.iat[i0,cols.index(t)])]
            ex_i=I[idx[idx>=pd.Timestamp(d.year+1,1,13)][0]] if (idx>=pd.Timestamp(d.year+1,1,13)).any() else len(idx)-1
            for _,j in sorted(ytd)[:3]:
                if j not in held: buy(j,0.10,"yearend",ex_i)
        if "tg" in rules and d.month==11:
            tgd=pd.Timestamp(d.year,11,1); tgd=tgd+pd.Timedelta(days=(3-tgd.dayofweek)%7+21)
            if d==tgd-pd.Timedelta(days=2):
                js=[cols.index(t) for t in NUC if ok.iat[i,cols.index(t)] and cols.index(t) not in held]
                for j in js: buy(j,0.15/len(js),"tg",i+2)
        if "panic" in rules and spy.iloc[i]/spy.iloc[i-1]-1<=-0.02:
            hits=[(R.iat[i,j],j) for j,t in enumerate(C.columns) if t in NUC and ok.iat[i,j] and R.iat[i,j]<=-0.03 and C.iat[i,j]/HI20.iat[i,j]-1<=-0.15]
            fill=[(C.iat[i,j]/HI20.iat[i,j]-1,j) for j,t in enumerate(C.columns) if t in REL and ok.iat[i,j] and R.iat[i,j]<=-0.03 and C.iat[i,j]/HI20.iat[i,j]-1<=-0.15]
            fill2=[(C.iat[i,j]/HI20.iat[i,j]-1,j) for j,t in enumerate(C.columns) if PW and t in TIER2 and ok.iat[i,j] and R.iat[i,j]<=-0.03 and C.iat[i,j]/HI20.iat[i,j]-1<=-0.15]
            picks=[j for _,j in sorted(hits)]+[j for _,j in sorted(fill)]+[j for _,j in sorted(fill2)]
            npan=sum(1 for p in pos if p['k']=="panic")
            for j in picks[:max(0,3-npan)]:
                if j in held: continue
                vx=vix.iloc[i]; s=1 if (vx<25 or vx>=40) else -1; s+=1 if R.iat[i,j]<=-0.08 else (-1 if R.iat[i,j]>-0.05 else 0)
                step=[10,15,25,40,50][max(0,min(4,2+s))] if above.iloc[i] else 10
                buy(j,step/100,"panic")
        if "sharp" in rules:
            ns=sum(1 for p in pos if p['k']=="sharp")
            kf=(lambda j:R.iat[i,j]) if RANK=='today' else (lambda j:r5.iat[i,j])
            c1=sorted([j for j,t in enumerate(C.columns) if t in U and ok.iat[i,j] and r5.iat[i,j]<=-0.15 and j not in held], key=kf)
            if F3: c1=c1+sorted([j for j,t in enumerate(C.columns) if t in U and ok.iat[i,j] and not r5.iat[i,j]<=-0.15 and C.iat[i,j]/C.iat[i-3,j]-1<=-0.12 and j not in held and j not in c1], key=lambda j:R.iat[i,j])
            c2=sorted([j for j,t in enumerate(C.columns) if t in TIER2 and ok.iat[i,j] and r5.iat[i,j]<=-0.15 and j not in held], key=lambda j:R.iat[i,j])
            for j in (c1+c2)[:max(0,SLOTS-ns)]:
                buy(j,(0.15 if r5.iat[i,j]<=-0.20 else 0.10)*(VS if vix.iloc[i]>30 else 1),"sharp")
        if "comeback" in rules and not above.iloc[i] and i>0:
            nc=sum(1 for p in pos if p['k']=="comeback")
            cands=[j for j,t in enumerate(C.columns) if (t in U or (CW and t in TIER2)) and ok.iat[i,j] and j not in held and L.iat[i,j]/C.iat[i-1,j]-1<=-0.06 and C.iat[i,j]>C.iat[i-1,j]]
            cands=sorted(cands,key=lambda j:0 if C.columns[j] in U else 1)
            for j in cands[:max(0,3-nc)]: buy(j,0.10,"comeback")
    e=pd.Series(curve,index=days); y=(days[-1]-days[0]).days/365.25
    yr=e.resample("YE").last(); yr=pd.concat([pd.Series([1000.0],index=[days[0]]),yr]).pct_change().dropna()*100
    return e,(e.iloc[-1]/1000)**(1/y)-1,(e/e.cummax()-1).min(),ntr,yr


allr=("panic","sharp","comeback","fear","ai","yearend","tg")
e,cg,dd,n,yr=run("2008-01-01",rules=allr,brake=0.25)
e1=e.loc[:"2018-12-31"]; e2=e.loc["2019-01-01":]
f=lambda x:((x.iloc[-1]/x.iloc[0])**(365.25/(x.index[-1]-x.index[0]).days)-1)*100
print(f"PANICADD={int(PADD)} RANK={RANK} PARK={PARK} FAST3={int(F3)} PANICWIDE={int(PW)} CBWIDE={int(CW)} VIXSHARP={VS} WIDE={os.environ.get('WIDE','0')} SLOTS={SLOTS}: {cg*100:5.1f}%/yr (08-18 {f(e1):5.1f}%, 19-26 {f(e2):5.1f}%) worst {dd*100:6.1f}% (08-18 {((e1/e1.cummax()-1).min())*100:.1f}, 19-26 {((e2/e2.cummax()-1).min())*100:.1f}) | ${e.iloc[-1]:,.0f} | sharp trades {n['sharp']}",flush=True)
