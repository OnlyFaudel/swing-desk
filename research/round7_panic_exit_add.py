import pandas as pd, numpy as np, json
D=pd.read_pickle('/tmp/sz/daily_max.pkl'); D=D[D.index>='2007-01-01']; C,H,V=D['Close'],D['High'],D['Volume']
spy=C['SPY']; sr=spy.pct_change(); R=C.pct_change(); cost=0.002
cfg=json.load(open('/home/claude/swing-desk/config.json'))
NUC=["CCJ","NXE","UEC","DNN","UUUU","LEU","BWXT","CEG","VST","TLN"]; REL=[t for t in cfg['panic_rebound']['related_universe'] if t in C and t not in NUC]
U=[t for t in NUC+REL if t in C]; HI20=H.rolling(20).max(); dv=(C*V).rolling(20).mean(); hold=6
rows=[]
for i in np.where((sr<=-0.02).values)[0]:
    if i+12>=len(C) or i<25: continue
    spy0=spy.iloc[i-1]  # S&P close before the panic day
    for t in U:
        c=C[t]; e=c.iloc[i]
        if not (e>=3 and dv[t].iloc[i]>=5e6 and R[t].iloc[i]<=-0.03 and e/HI20[t].iloc[i]-1<=-0.15): continue
        # live exit: +10% at a close or day 6
        xi=i+hold
        for k in range(i+1,i+hold+1):
            if c.iloc[k]>=e*1.10: xi=k; break
        live=(c.iloc[xi]/e-1)-cost-(spy.iloc[xi]/spy.iloc[i]-1)
        # O: market exit: first close where S&P is back above its pre-panic close (or +10%), max 6 days
        xo=i+hold
        for k in range(i+1,i+hold+1):
            if c.iloc[k]>=e*1.10 or spy.iloc[k]>=spy0: xo=k; break
        mkt=(c.iloc[xo]/e-1)-cost-(spy.iloc[xo]/spy.iloc[i]-1)
        # Q: second buy if it closes 10% under the entry before the live exit; tranche 2 sold with the trade (+10% from blended)
        sec=None; cst=e; xa=i+hold; a_i=None
        for k in range(i+1,i+hold+1):
            if a_i is None and c.iloc[k]<=e*0.90: a_i=k; cst=(e+c.iloc[k])/2
            if c.iloc[k]>=cst*1.10: xa=k; break
        if a_i is not None and a_i<xa: sec=(c.iloc[xa]/c.iloc[a_i]-1)-cost-(spy.iloc[xa]/spy.iloc[a_i]-1)
        rows.append(dict(d=C.index[i],yr=C.index[i].year,t=t,live=live,mkt=mkt,sec=sec,days_live=xi-i,days_mkt=xo-i))
X=pd.DataFrame(rows)
# one point per panic day (average across the stocks bought that day)
E=X.groupby('d').agg(yr=('yr','first'),live=('live','mean'),mkt=('mkt','mean'),dl=('days_live','mean'),dm=('days_mkt','mean'))
for era,m in (('08-18',E.yr<=2018),('19-26',E.yr>=2019)):
    y=E[m]; d=y.mkt-y.live
    print(f'O {era} days={len(y):3d} live {y.live.mean()*100:+.2f}% ({y.dl.mean():.1f} days held) | market-exit {y.mkt.mean()*100:+.2f}% ({y.dm.mean():.1f} days) | difference {d.mean()*100:+.2f}% (t {d.mean()/d.std()*np.sqrt(len(d)):.1f})')
S=X.dropna(subset=['sec']).groupby('d').agg(yr=('yr','first'),sec=('sec','mean'))
for era,m in (('08-18',S.yr<=2018),('19-26',S.yr>=2019)):
    y=S[m].sec; print(f'Q {era} panic days with a second buy={len(y):3d} | second buy vs S&P {y.mean()*100:+.2f}% (t {y.mean()/y.std()*np.sqrt(len(y)) if len(y)>2 else 0:.1f}, up {(y>0).mean()*100:.0f}%)')
