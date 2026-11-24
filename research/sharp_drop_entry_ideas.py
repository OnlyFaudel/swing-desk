import pandas as pd, numpy as np
D=pd.read_pickle('/tmp/sz/daily_max.pkl')
D=D[D.index>='2006-01-01']
O,H,C,V=D['Open'],D['High'],D['Close'],D['Volume']
uni=[t for t in C.columns if t not in('SPY','URA','URNM')]
spy=C['SPY']; cost=0.002
def run(entry='close', add=False):
    rows=[]
    for t in uni:
        c=C[t]; v=V[t]
        if c.notna().sum()<300: continue
        r5=c/c.shift(5)-1; dv=(c*v).rolling(20).mean(); vol=c.pct_change().rolling(20).std()
        sig=((r5<=-0.15)&(c>=3)&(dv>=5e6)).fillna(False).values
        i=25; n=len(c)
        while i<n-12:
            if not sig[i]: i+=1; continue
            j=i
            if entry=='green':  # wait for first up close within 3 days
                j=None
                for k in range(i+1,min(i+4,n-12)):
                    if c.iloc[k]>c.iloc[k-1]: j=k;break
                if j is None: i+=4; continue
            e=c.iloc[j]; qty=1.0; cst=e
            x=None; xi=None
            for k in range(j+1,min(j+11,n)):
                if add and qty==1.0 and c.iloc[k]<=e*0.90:  # add same size again after another 10% fall
                    qty=2.0; cst=(e+c.iloc[k])/2
                if c.iloc[k]>=cst*1.10: x=c.iloc[k]; xi=k; break
            if x is None: xi=min(j+10,n-1); x=c.iloc[xi]
            ret=(x/cst-1)-cost
            rows.append(dict(t=t,yr=c.index[j].year,ret=ret*qty,qty=qty,spy=spy.iloc[xi]/spy.iloc[j]-1,vol=vol.iloc[j]))
            i=xi+1
    return pd.DataFrame(rows)
def rep(R,label,w=None):
    for era,m in (('2008-18',(R.yr>=2008)&(R.yr<=2018)),('2019-26',R.yr>=2019)):
        d=R[m]; ww=np.ones(len(d)) if w is None else w[m.values]
        ex=(d.ret-d.spy)*ww
        print(f"{label:34s} {era} n={len(d):4d} avg {np.average(d.ret,weights=None)*100 if w is None else (d.ret*ww).mean()*100:+.2f}%  vs S&P {ex.mean()*100:+.2f}% (t {ex.mean()/ex.std()*np.sqrt(len(ex)):.1f})  worst5% {np.percentile(d.ret*ww,5)*100:+.1f}%  mean/sd {(d.ret*ww).mean()/(d.ret*ww).std():.3f}")
base=run('close'); rep(base,'live: buy the drop at the close')
# B: inverse-volatility sizing (normalized to mean 1 within each era, capped 0.5-1.5)
w=(base.vol.median()/base.vol).clip(0.5,1.5); w=w/w.mean(); rep(base,'B: size by 1/volatility',w.values)
g=run('green'); rep(g,'C: wait for first green close')
a=run('close',add=True); rep(a,'D: add again after another -10%')
print('D adds happened in', (a.qty>1).mean()*100,'% of trades')
print('--- second buy on its own (bought 10% lower, sold with the trade) ---')
rows=[]
for t in uni:
    c=C[t]; v=V[t]
    if c.notna().sum()<300: continue
    r5=c/c.shift(5)-1; dv=(c*v).rolling(20).mean()
    sig=((r5<=-0.15)&(c>=3)&(dv>=5e6)).fillna(False).values
    i=25; n=len(c)
    while i<n-12:
        if not sig[i]: i+=1; continue
        e=c.iloc[i]; a_i=None; cst=e; x=None
        for k in range(i+1,min(i+11,n)):
            if a_i is None and c.iloc[k]<=e*0.90: a_i=k; cst=(e+c.iloc[k])/2
            if c.iloc[k]>=cst*1.10: x=c.iloc[k]; xi=k; break
        if x is None: xi=min(i+10,n-1); x=c.iloc[xi]
        if a_i is not None:
            rows.append(dict(yr=c.index[a_i].year, first=x/e-1-cost, second=x/c.iloc[a_i]-1-cost, spy2=spy.iloc[xi]/spy.iloc[a_i]-1, days2=xi-a_i, days1=xi-i))
        i=xi+1
T2=pd.DataFrame(rows)
for era,m in (('2008-18',(T2.yr>=2008)&(T2.yr<=2018)),('2019-26',T2.yr>=2019)):
    d=T2[m]; ex=d.second-d.spy2
    print(era,'n',len(d),'second buy avg %+.2f%% vs S&P %+.2f%% (t %.1f) worst5%% %+.1f%%, held %.1f days | first buy in those same trades %+.2f%%'%(d.second.mean()*100, ex.mean()*100, ex.mean()/ex.std()*np.sqrt(len(d)), np.percentile(d.second,5)*100, d.days2.mean(), d.first.mean()*100))
