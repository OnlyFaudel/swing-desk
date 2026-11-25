import pandas as pd, numpy as np, json
D=pd.read_pickle('/tmp/sz/daily_max.pkl'); D=D[D.index>='2007-01-01']; C=D['Close']; V=D['Volume']
W=pd.read_pickle('/tmp/wide/wide.pkl')['Close']; W=W[[t for t in W.columns if t not in C.columns]].reindex(C.index)
A=pd.concat([C,W],axis=1); spy=C['SPY']; cost=0.002
X=pd.read_pickle('/tmp/sz/cross.pkl')['Close'].reindex(C.index).ffill()
cfg=json.load(open('/home/claude/swing-desk/config.json'))
NUC=["CCJ","NXE","UEC","DNN","UUUU","LEU","BWXT","CEG","VST","TLN"]; REL=[t for t in cfg['panic_rebound']['related_universe'] if t in C and t not in NUC]
WIDE=list(W.columns); idx=C.index
def win(names,i0,i1):
    r=[(A[t].iloc[i1]/A[t].iloc[i0]-1) for t in names if t in A and np.isfinite(A[t].iloc[i0]) and np.isfinite(A[t].iloc[i1]) and A[t].iloc[i0]>=3]
    return (np.mean(r) if r else np.nan), (spy.iloc[i1]/spy.iloc[i0]-1)
def era(rows,label):
    x=pd.DataFrame(rows,columns=['yr','r','s']); x['e']=x.r-x.s-cost
    for e,m in (('2008-18',x.yr<=2018),('2019-25',x.yr>=2019)):
        y=x[m].dropna()
        print(f'{label:58s} {e} yrs={len(y):2d} | avg {y.r.mean()*100:+.2f}% vs S&P {y.e.mean()*100:+.2f}% (t {y.e.mean()/y.e.std()*np.sqrt(len(y)):.1f}, beat in {(y.e>0).sum()}/{len(y)})')
print('== 1 SANTA RALLY: buy the close 6 sessions before the last December session, sell the close of the 2nd January session')
for lab,names in (('our 10',NUC),('related',REL),('115 big stocks',WIDE)):
    rows=[]
    for y in range(2007,2026):
        dec=idx[(idx.year==y)&(idx.month==12)]; jan=idx[(idx.year==y+1)&(idx.month==1)]
        if len(dec)<6 or len(jan)<2: continue
        i0=idx.get_loc(dec[-6]); i1=idx.get_loc(jan[1]); r,s=win(names,i0,i1); rows.append((y,r,s))
    era(rows,'Santa rally: '+lab)
# random 7-session windows in Dec-Jan for comparison
print('== 2 RUSSELL RECONSTITUTION (calendar proxy: no membership data): small nuclear names May 15 -> last Friday of June, then 2 weeks after')
SMALL=['UUUU','UEC','DNN','NXE','URG','NNE','SMR','OKLO','LEU','LTBR','ASPI']
for lab,(a,b) in (('run-up May 15 -> recon day',(0,1)),('after: recon day -> +10 sessions',(1,2))):
    rows=[]
    for y in range(2008,2026):
        jun=idx[(idx.year==y)&(idx.month==6)]; fr=[d for d in jun if d.weekday()==4]
        if not fr: continue
        rd=idx.get_loc(fr[-1]); st=idx.get_loc(idx[idx>=pd.Timestamp(y,5,15)][0])
        pts=[st,rd,min(rd+10,len(idx)-1)]; r,s=win(SMALL,pts[a],pts[b]); rows.append((y,r,s))
    era(rows,'Russell: '+lab)
print('== 4 YEAR-END BOUNCE on more stocks: 5 worst year-to-date, buy ~Dec 20 close, sell ~Jan 15 close')
for lab,names in (('our 10 (live rule, 3 worst)',NUC),('related',REL),('115 big stocks',WIDE)):
    rows=[]; k=3 if 'our 10' in lab else 5
    for y in range(2007,2026):
        b=idx[idx>=pd.Timestamp(y,12,20)]; s_=idx[idx>=pd.Timestamp(y+1,1,15)]; y0=idx[idx.year==y]
        if not len(b) or not len(s_) or not len(y0): continue
        i0,i1,iy=idx.get_loc(b[0]),idx.get_loc(s_[0]),idx.get_loc(y0[0])
        ytd={t:A[t].iloc[i0]/A[t].iloc[iy]-1 for t in names if t in A and np.isfinite(A[t].iloc[i0]) and np.isfinite(A[t].iloc[iy]) and A[t].iloc[i0]>=3}
        losers=sorted(ytd,key=ytd.get)[:k]; r,s=win(losers,i0,i1); rows.append((y,r,s))
    era(rows,'Year-end losers: '+lab)
print('== 5 KAZATOMPROM (London) big day -> our miners from that US close')
kap=X['KAP.L']; kr=kap.pct_change(); MIN=['CCJ','NXE','UEC','DNN','UUUU']
for thr,sign in ((0.04,1),(0.04,-1),(0.06,1),(0.06,-1)):
    rows=[]
    for i in np.where(((kr*sign)>=thr).values)[0]:
        if i+5>=len(idx): continue
        r1,s1=win(MIN,i,i+1); r5,s5=win(MIN,i,i+5); same,_=win(MIN,i-1,i)
        rows.append((idx[i].year,r1-s1,r5-s5,same))
    x=pd.DataFrame(rows,columns=['yr','x1','x5','same'])
    for e,m in (('2008-18',x.yr<=2018),('2019-26',x.yr>=2019)):
        y=x[m]
        if len(y)<5: print(f'KAP {"+" if sign>0 else "-"}{int(thr*100)}% {e} n={len(y)}'); continue
        print(f'KAP {"+" if sign>0 else "-"}{int(thr*100)}% day {e} n={len(y):3d} | miners same day {y.same.mean()*100:+.2f}% (already moved) | next day vs S&P {y.x1.mean()*100:+.2f}% (t {y.x1.mean()/y.x1.std()*np.sqrt(len(y)):.1f}) | 5 days {y.x5.mean()*100:+.2f}% (t {y.x5.mean()/y.x5.std()*np.sqrt(len(y)):.1f})')
