import pandas as pd, numpy as np, json
D=pd.read_pickle('/tmp/sz/daily_max.pkl'); D=D[D.index>='2007-01-01']; C,H,V=D['Close'],D['High'],D['Volume']
X=pd.read_pickle('/tmp/sz/cross.pkl')['Close'].reindex(C.index).ffill(); smh=X['SMH'].pct_change()
spy=C['SPY']; sr=spy.pct_change(); R=C.pct_change(); cost=0.002
cfg=json.load(open('/home/claude/swing-desk/config.json'))
NUC=["CCJ","NXE","UEC","DNN","UUUU","LEU","BWXT","CEG","VST","TLN"]; REL=[t for t in cfg['panic_rebound']['related_universe'] if t in C and t not in NUC]
U=[t for t in NUC+REL if t in C]; HI20=C.rolling(20).max(); dv=(C*V).rolling(20).mean()
def evrep(days, names, label, hold=6):
    ev=[]
    last=-99
    for i in days:
        if i-last<hold or i+hold>=len(C): continue
        picks=[t for t in names if C[t].iloc[i]>=3 and dv[t].iloc[i]>=5e6 and R[t].iloc[i]<=-0.03 and C[t].iloc[i]/HI20[t].iloc[i]-1<=-0.15]
        if not picks: continue
        last=i; rs=[]
        for t in picks:
            e=C[t].iloc[i]; x=C[t].iloc[i+hold]; xi=i+hold
            for k in range(i+1,i+hold+1):
                if C[t].iloc[k]>=e*1.10: x=C[t].iloc[k]; xi=k; break
            rs.append((x/e-1)-cost-(spy.iloc[xi]/spy.iloc[i]-1))
        ev.append((C.index[i].year,np.mean(rs),len(picks)))
    E=pd.DataFrame(ev,columns=['yr','x','n'])
    for era,m in (('08-18',E.yr<=2018),('19-26',E.yr>=2019)):
        y=E[m].x; print(f'{label:58s} {era} days={len(y):3d} {y.mean()*100:+.2f}% vs S&P per day (t {y.mean()/y.std()*np.sqrt(len(y)) if len(y)>2 else 0:.1f}, up {(y>0).mean()*100:.0f}%)')
spyp=np.where((sr<=-0.02).values)[0]
evrep(spyp,U,'panic days as live (S&P -2%), for reference')
tech=np.where(((smh<=-0.03)&(sr>-0.02)).values)[0]
evrep(tech,U,'I tech-panic: SMH -3%+, S&P not -2% (new days)')
evrep(tech,NUC,'I tech-panic, our 10 only')
evrep(np.where(((smh<=-0.04)&(sr>-0.02)).values)[0],U,'I tech-panic stricter: SMH -4%+')
# J: 3-day 12% drop not already a 5-day 15% drop
r3=C/C.shift(3)-1; r5=C/C.shift(5)-1; rows=[]
for t in U:
    c=C[t]; sig=((r3[t]<=-0.12)&~(r5[t]<=-0.15)&(c>=3)&(dv[t]>=5e6)).fillna(False).values; i=25; n=len(c)
    while i<n-12:
        if not sig[i]: i+=1; continue
        e=c.iloc[i]; x=None
        for k in range(i+1,min(i+11,n)):
            if c.iloc[k]>=e*1.10: x=c.iloc[k]; xi=k; break
        if x is None: xi=min(i+10,n-1); x=c.iloc[xi]
        rows.append((c.index[i].year,(x/e-1)-cost-(spy.iloc[xi]/spy.iloc[i]-1))); i=xi+1
J=pd.DataFrame(rows,columns=['yr','x'])
for era,m in (('08-18',J.yr<=2018),('19-26',J.yr>=2019)):
    y=J[m].x; print(f'{"J 12%+ in 3 days, not yet 15% in 5 (new trades)":58s} {era} n={len(y):4d} {y.mean()*100:+.2f}% vs S&P (t {y.mean()/y.std()*np.sqrt(len(y)):.1f})')
