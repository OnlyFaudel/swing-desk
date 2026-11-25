import pandas as pd, numpy as np, json
D=pd.read_pickle('/tmp/sz/daily_max.pkl'); D=D[D.index>='2007-01-01']; C,V=D['Close'],D['Volume']
W=pd.read_pickle('/tmp/wide/wide.pkl')['Close'].reindex(C.index)
spy=C['SPY']; cost=0.002
cfg=json.load(open('/home/claude/swing-desk/config.json'))
NUC=["CCJ","NXE","UEC","DNN","UUUU","LEU","BWXT","CEG","VST","TLN"]; REL=[t for t in cfg['panic_rebound']['related_universe'] if t in C and t not in NUC]
U=[t for t in NUC+REL if t in C]
r5=C/C.shift(5)-1; dv=(C*V).rolling(20).mean(); sma200=C.rolling(200).mean()
grp5=r5[U].median(axis=1)  # the nuclear+related group's typical 5-day move
rows=[]
for t in U:
    c=C[t]; sig=((r5[t]<=-0.15)&(c>=3)&(dv[t]>=5e6)).fillna(False).values; i=210; n=len(c)
    while i<n-12:
        if not sig[i]: i+=1; continue
        e=c.iloc[i]; x=None
        for k in range(i+1,min(i+11,n)):
            if c.iloc[k]>=e*1.10: x=c.iloc[k]; xi=k; break
        if x is None: xi=min(i+10,n-1); x=c.iloc[xi]
        rows.append(dict(t=t,d=c.index[i],yr=c.index[i].year,ex=(x/e-1)-cost-(spy.iloc[xi]/spy.iloc[i]-1),
                         grp=grp5.iloc[i],own=r5[t].iloc[i],above200=bool(e>sma200[t].iloc[i]) if np.isfinite(sma200[t].iloc[i]) else None))
        i=xi+1
R=pd.DataFrame(rows); R['idio']=R.own-R.grp
def show(df,label):
    out=[]
    for era,m in (('08-18',df.yr<=2018),('19-26',df.yr>=2019)):
        y=df[m].ex; out.append(f'{era} n={len(y):4d} {y.mean()*100:+.2f}% (t {y.mean()/y.std()*np.sqrt(len(y)):.1f})' if len(y)>5 else f'{era} n={len(y)}')
    print(f'{label:48s} '+' | '.join(out))
show(R,'B/C all sharp-drop trades vs S&P')
show(R[R.grp<=-0.08],'B group fell 8%+ too (group-wide selling)')
show(R[R.grp>-0.03],'B group roughly flat (stock fell alone)')
show(R[R.above200==True],'C above its 200-day average')
show(R[R.above200==False],'C below its 200-day average')
# E: capitulation breadth: share of the big stocks down on the day
br=(W.pct_change()<0).sum(axis=1)/W.notna().sum(axis=1)
L10=[t for t in NUC if t in C]; RL=REL
for thr in (0.85,0.90):
    ev=[]; last=-99
    for i in np.where((br>=thr).values)[0]:
        if i-last<5 or i+10>=len(C): continue
        last=i
        def g(names,n): 
            v=[(C[t].iloc[i+n]/C[t].iloc[i]-1) for t in names if np.isfinite(C[t].iloc[i]) and np.isfinite(C[t].iloc[i+n]) and C[t].iloc[i]>=3]
            return np.mean(v)-(spy.iloc[i+n]/spy.iloc[i]-1)-cost if v else np.nan
        ev.append(dict(yr=C.index[i].year,n10_5=g(L10,5),rel_5=g(RL,5),n10_10=g(L10,10),spy5=spy.iloc[i+5]/spy.iloc[i]-1))
    E=pd.DataFrame(ev)
    for era,m in (('08-18',E.yr<=2018),('19-26',E.yr>=2019)):
        y=E[m].dropna()
        f=lambda s:f'{s.mean()*100:+.2f}% (t {s.mean()/s.std()*np.sqrt(len(s)):.1f})'
        print(f'E capitulation (>= {int(thr*100)}% of big stocks down) {era} days={len(y):3d} | our 10 5d vs S&P {f(y.n10_5)} 10d {f(y.n10_10)} | related 5d {f(y.rel_5)} | S&P itself 5d {y.spy5.mean()*100:+.2f}%')
