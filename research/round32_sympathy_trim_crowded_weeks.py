import pandas as pd, numpy as np
E=pd.read_pickle('/tmp/sz/earn_events.pkl'); E['d']=pd.to_datetime(E.d)
C=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']; spy=C['SPY']; S=spy.pct_change(); R=C.pct_change()
grp={'miners':['CCJ','UEC','DNN','UUUU','NXE'],'power':['CEG','VST','TLN'],'fuel':['LEU','BWXT']}
G={t:g for g,ts in grp.items() for t in ts}; ours=list(G)
# days where a group mate jumped 5%+ on earnings
pop={}
for _,e in E.iterrows():
    if e.t in G and e.r0>=0.05:
        i=C.index.searchsorted(e.d)
        for p in grp[G[e.t]]:
            if p!=e.t: pop.setdefault(p,set()).add(i)
# live-style trades on our 10: panic (S&P -2%, stock -3%, 15% under 20d high) or sharp drop (-15% in 5d); +10% at a close or day N
hi20=C.rolling(20).max(); r5=C/C.shift(5)-1
rows=[]
for t in ours:
    c=C[t].values
    for i in range(25,len(c)-12):
        if np.isnan(c[i]): continue
        is_p=S.iloc[i]<=-0.02 and R[t].iloc[i]<=-0.03 and c[i]<=hi20[t].iloc[i]*0.85
        is_s=r5[t].iloc[i]<=-0.15
        if not(is_p or is_s): continue
        N=6 if is_p else 10
        # live exit
        ex=next((k for k in range(1,N+1) if c[i+k]>=c[i]*1.10),N)
        live=c[i+ex]/c[i]-1
        # sympathy trim: if a group mate pops on earnings on day k<ex, sell at that close
        k2=next((k for k in range(1,ex) if (i+k) in pop.get(t,())),None)
        if k2 is None: continue
        trim=c[i+k2]/c[i]-1
        rows.append((C.index[i],t,live,trim,k2,ex))
r=pd.DataFrame(rows,columns=['d','t','live','trim','k','ex'])
print('trades with a group-mate earnings pop during the hold:',len(r))
for era,(a,b) in {'2010-18':('2010','2019'),'2019-26':('2019','2027')}.items():
    x=r[(r.d>=a)&(r.d<b)]; print(era,'n',len(x),'live exit %+.2f%% | sell into the sympathy pop %+.2f%%'%(x.live.mean()*100,x.trim.mean()*100))
# sector earnings week: 3+ group reports within 5 sessions -> group basket during the week vs S&P
print('earnings-crowded weeks:')
for g,ts in grp.items():
    ev=sorted(C.index.searchsorted(E[E.t.isin(ts)].d))
    B=R[ts].mean(axis=1)-S
    wk=[]
    for j,i in enumerate(ev):
        cnt=sum(1 for x in ev if i<=x<i+5)
        if cnt>=min(3,len(ts)) and (not wk or i-wk[-1]>10): wk.append(i)
    vals=[(C.index[i],B.iloc[i:i+5].sum(),B.iloc[i+5:i+15].sum()) for i in wk if i+15<len(B)]
    v=pd.DataFrame(vals,columns=['d','during','after'])
    for era,(a,b) in {'2010-18':('2010','2019'),'2019-26':('2019','2027')}.items():
        x=v[(v.d>=a)&(v.d<b)]
        print(f"  {g:7s} {era}: during the crowded week {x.during.mean()*100:+.2f}% | next 2 weeks {x.after.mean()*100:+.2f}% n{len(x)}")
