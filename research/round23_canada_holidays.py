import pandas as pd, numpy as np, datetime as dt
d=pd.read_pickle('/tmp/sz/daily_max.pkl'); C=d['Close']; V=d['Volume']
dual=[t for t in ['CCJ','NXE','DNN'] if t in C]; us=[t for t in ['UEC','LEU','BWXT','UUUU'] if t in C]
def hol(y):
    out=[]
    m=dt.date(y,5,24); 
    while m.weekday()!=0: m-=dt.timedelta(1)
    out.append(m)
    c=dt.date(y,7,1); c = c if c.weekday()<5 else (c+dt.timedelta(1) if c.weekday()==6 else c+dt.timedelta(2)); out.append(c)
    a=dt.date(y,8,1)
    while a.weekday()!=0: a+=dt.timedelta(1)
    out.append(a)
    o=dt.date(y,10,1)
    while o.weekday()!=0: o+=dt.timedelta(1)
    out.append(o+dt.timedelta(7))
    b=dt.date(y,12,26)
    if b.weekday()<5: out.append(b)
    return out
days=[pd.Timestamp(x) for y in range(2005,2027) for x in hol(y)]
R=C.pct_change(); rows=[]
for x in days:
    if x not in C.index: continue
    i=C.index.get_loc(x)
    for t in dual:
        if pd.isna(R[t].iloc[i]) or pd.isna(R[t].iloc[i+1]) : continue
        vr=V[t].iloc[i]/V[t].iloc[i-21:i-1].mean()
        rows.append((x,t,R[t].iloc[i]-R['SPY'].iloc[i],R[t].iloc[i+1]-R['SPY'].iloc[i+1],(C[t].iloc[i+5]/C[t].iloc[i]-1)-(C['SPY'].iloc[i+5]/C['SPY'].iloc[i]-1),vr,abs(R[t].iloc[i])))
r=pd.DataFrame(rows,columns=['d','t','day','next','next5','volratio','absmove'])
norm=pd.concat([(R[t]-R.SPY).abs() for t in dual]).dropna()
for lab,m in (('2005-18',r.d<'2019'),('2019-26',r.d>='2019')):
    g=r[m]; print(lab,'n',len(g),'US-only day vs S&P %+.2f%%'%(g.day.mean()*100),'abs move %.2f%% (normal %.2f%%)'%(g.absmove.mean()*100,norm.mean()*100),
          'volume x%.2f of normal'%g.volratio.median(),'next day %+.2f%%'%(g.next.mean()*100),'next 5 %+.2f%%'%(g.next5.mean()*100),
          '| big move day (>3%%) next-day reversal %+.2f%% n%d'%((-np.sign(g.day)*g.next)[g.day.abs()>0.03].mean()*100,(g.day.abs()>0.03).sum()))
