exec(open('base.py').read())
WIDE=[t for t in C.columns if t not in U and t not in ('SPY','QQQ','SSO','QLD','URA','URNM','XLU','SMH','SGOV') and not t.startswith('^')]
def hol_name(h):
    m,d=h.month,h.day
    return {1:'NewYear/MLK',2:'Presidents',4:'GoodFriday',3:'GoodFriday',5:'Memorial',6:'Juneteenth',7:'July4',9:'LaborDay',11:'Thanksgiving',12:'Christmas'}.get(m,'other')
def run_hol(uni,k,days_before=3,exit_after=0):
    rows=[];hs=set()
    for h in hol:
        ia=idx.searchsorted(h)
        if ia>=len(idx)-3 or ia<4: continue
        for i in range(ia-days_before,ia):
            hs.add(i)
            for t in uni:
                r=limit_trade(t,i,k,min(ia+exit_after,len(idx)-1))
                if r is not None: rows.append(dict(d=idx[i],t=t,r=r,h=hol_name(h),y=h.year))
    return pd.DataFrame(rows),hs
def ctrl_run(uni,k,hs,hold=2,step=3):
    rows=[]
    for i in range(260,len(idx)-hold-1,step):
        if i in hs: continue
        for t in uni:
            r=limit_trade(t,i,k,i+hold)
            if r is not None: rows.append(dict(d=idx[i],t=t,r=r))
    return pd.DataFrame(rows)
def line(df,cdf,name):
    df=df.copy(); df['era']=df.d.map(era); cdf=cdf.copy(); cdf['era']=cdf.d.map(era)
    s=[]
    for e in ('2007-18','2019-25'):
        g=df[df.era==e]; c=cdf[cdf.era==e]
        per=g.groupby('d').r.mean(); t=per.mean()/(per.std()/np.sqrt(len(per)))
        s.append(f"{e}: {g.r.mean()*100:+.2f}%/buy vs ordinary {c.r.mean()*100:+.2f}% (edge {(g.r.mean()-c.r.mean())*100:+.2f}, days {len(per)}, t {t:.1f})")
    print(f"{name}\n   "+"\n   ".join(s),flush=True)
print("C2. Pre-holiday limit dips, robustness")
for uni,un in ((NUC,'nuclear only'),(U,'nuclear+related'),(WIDE,'INDEPENDENT: ~600 other stocks')):
    for k in (0.02,0.03,0.04):
        df,hs=run_hol(uni,k); cdf=ctrl_run(uni,k,hs)
        line(df,cdf,f"[{un}] limit {k*100:.0f}%")
df,hs=run_hol(U,0.03)
print("\nBy holiday (nuclear+related, 3%): avg per buy", df.groupby('h').r.agg(lambda x:round(x.mean()*100,2)).to_dict())
print("Share of holidays where the trades made money on average:", round((df.groupby(['y','h']).r.mean()>0).mean()*100),"%  of", df.groupby(['y','h']).ngroups)
for dbf in (1,2):
    df,hs=run_hol(U,0.03,days_before=dbf); cdf=ctrl_run(U,0.03,hs); line(df,cdf,f"[nuclear+related] 3%, only the last {dbf} day(s) before")
df,hs=run_hol(U,0.03,exit_after=2); cdf=ctrl_run(U,0.03,hs,hold=4); line(df,cdf,"[nuclear+related] 3%, hold 2 more sessions after the holiday")
print("\nB2. Thanksgiving-week 5% limit, INDEPENDENT check on ~600 other stocks:")
rows=[];ctrl=[]
for tg in TG:
    i_mon=idx.searchsorted(tg-pd.Timedelta(days=3)); i_fri=idx.searchsorted(tg+pd.Timedelta(days=1))
    for i in range(i_mon,i_fri):
        for t in WIDE:
            r=limit_trade(t,i,0.05,i_fri)
            if r is not None: rows.append(dict(d=idx[i],t=t,r=r))
for i in range(260,len(idx)-5,2):
    d=idx[i]
    if d.dayofweek>2 or (d.month==11 and 20<=d.day<=27): continue
    for t in WIDE:
        r=limit_trade(t,i,0.05,min(i+(3-d.dayofweek),len(idx)-1))
        if r is not None: ctrl.append(dict(d=d,t=t,r=r))
line(pd.DataFrame(rows),pd.DataFrame(ctrl),"   other stocks, Thanksgiving week 5% limit, sell Black Friday")
b=pd.DataFrame(rows); b['y']=b.d.dt.year; print("   by year:",b.groupby('y').r.mean().mul(100).round(1).to_dict())
