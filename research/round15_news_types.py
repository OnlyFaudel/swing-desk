import pandas as pd, numpy as np, json
D=pd.read_pickle('/tmp/sz/daily_max.pkl'); C=D['Close']; spy=C['SPY']; idx=C.index; cost=0.002
A=json.load(open('/home/claude/swing-desk/memory/archive_events.json'))
G={'miners':['CCJ','NXE','UEC','DNN','UUUU'],'fuel/tech':['LEU','BWXT'],'power':['CEG','VST','TLN']}
grp=lambda t:next((g for g,m in G.items() if t in m),'other')
res=[]
for ty in sorted({e['type'] for e in A if e['type'].startswith('news_')}):
    for g in ('miners','fuel/tech','power','all'):
        rows=[]; last={}
        for e in sorted([e for e in A if e['type']==ty and (g=='all' or grp(e['ticker'])==g)],key=lambda e:e['date']):
            t=e['ticker']
            if t not in C: continue
            i=idx.searchsorted(pd.Timestamp(e['date']))+1
            if i+20>=len(idx) or (t in last and i-last[t]<5): continue
            a=C[t].iloc[i]
            if not np.isfinite(a): continue
            last[t]=i
            rows.append((idx[i].year,(C[t].iloc[i+5]/a-1)-(spy.iloc[i+5]/spy.iloc[i]-1)-cost,(C[t].iloc[i+20]/a-1)-(spy.iloc[i+20]/spy.iloc[i]-1)-cost))
        x=pd.DataFrame(rows,columns=['yr','x5','x20']).dropna()
        if len(x)<30: continue
        h1,h2=x[x.yr<=2022],x[x.yr>=2023]
        if len(h1)<12 or len(h2)<12: continue
        tt=lambda s:s.mean()/s.std()*np.sqrt(len(s))
        res.append((ty,g,len(h1),h1.x5.mean(),tt(h1.x5),h1.x20.mean(),tt(h1.x20),len(h2),h2.x5.mean(),tt(h2.x5),h2.x20.mean(),tt(h2.x20)))
print(f'{"news type -> next close vs S&P":30s}{"group":10s}   2019-22: 5d / 20d              2023-26: 5d / 20d')
for r in res:
    same=(np.sign(r[3])==np.sign(r[8]) and abs(r[4])>1.5 and abs(r[9])>1.5) or (np.sign(r[5])==np.sign(r[10]) and abs(r[6])>1.5 and abs(r[11])>1.5)
    print(f'{r[0]:30s}{r[1]:10s} n{r[2]:4d} {r[3]*100:+5.2f}% t{r[4]:4.1f} {r[5]*100:+6.2f}% t{r[6]:4.1f} | n{r[7]:4d} {r[8]*100:+5.2f}% t{r[9]:4.1f} {r[10]*100:+6.2f}% t{r[11]:4.1f}'+('  <- consistent' if same else ''))
