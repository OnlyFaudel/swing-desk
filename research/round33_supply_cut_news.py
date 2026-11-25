import json,re,pandas as pd,numpy as np
E=pd.DataFrame(json.load(open('/home/claude/swing-desk/memory/archive_events.json')))
H=pd.DataFrame(json.load(open('/home/claude/swing-desk/memory/history_events.json')))
C=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']; spy=C['SPY']
miners=['CCJ','UEC','DNN','UUUU','NXE']
cut=re.compile(r"\b(cut|cuts|lower|lowers|lowered|reduce|reduces|reduced|curtail|suspend|suspends|suspended|halt|halts|halted|shortfall|delay|delays|delayed|downgrade|below (guidance|target)|miss|shut|shutdown|outage|flood|fire)\b",re.I)
up=re.compile(r"\b(raise|raises|raised|increase|increases|increased|boost|expand|expands|ramp|restart|record|above guidance|beat)\b",re.I)
P=E[E.type=='news_production'].copy(); P['d']=pd.to_datetime(P.date)
print('production news',len(P),P.d.min().date(),P.d.max().date(),'by ticker',P.ticker.value_counts().head(8).to_dict())
P['kind']=np.where(P.title.str.contains(cut),'supply cut / problem',np.where(P.title.str.contains(up),'more supply','other'))
B=C[miners].pct_change().mean(axis=1)
def fwd(i,h): 
    return (np.prod(1+B.iloc[i+1:i+1+h])-1)-(spy.iloc[i+h]/spy.iloc[i]-1)-0.002
rows=[]; seen={}
for _,e in P.sort_values('d').iterrows():
    i=C.index.searchsorted(e.d)
    if i+21>=len(C): continue
    k=e.kind
    if k in seen and i-seen[k]<10: continue   # one per 10 sessions per kind (news repeats)
    seen[k]=i; rows.append((e.d,k,e.ticker,fwd(i,5),fwd(i,20)))
r=pd.DataFrame(rows,columns=['d','kind','t','f5','f20'])
for lab,(a,b) in {'2019-22':('2019','2023'),'2023-26':('2023','2027')}.items():
    x=r[(r.d>=a)&(r.d<b)]
    print(lab,' | '.join(f"{k}: miners 5d {g.f5.mean()*100:+.2f}% 20d {g.f20.mean()*100:+.2f}% n{len(g)}" for k,g in x.groupby('kind')))
print(r[r.kind=='supply cut / problem'].tail(5).to_string())
print(P[P.kind=='supply cut / problem'].title.head(8).tolist())
