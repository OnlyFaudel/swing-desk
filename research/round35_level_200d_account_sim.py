import pandas as pd, numpy as np
tr=pd.read_pickle('/tmp/r34/tr2.pkl')
lineup=['CCJ','NXE','UEC','DNN','UUUU','LEU','BWXT','CEG','VST','TLN']
def sim(df,mode,size=0.20,maxpos=4):
    df=df.sort_values('entry'); eq=1.0; peak=1.0; mdd=0; open_=[]; curve=[]
    ev=[]
    for _,x in df.iterrows(): ev.append((x.entry,0,x)); ev.append((x.exit,1,x))
    ev.sort(key=lambda e:(e[0], 0 if (e[1]==1 and e[2].entry<e[0]) else (1 if e[1]==0 else 2)))
    held={}; cash=1.0; n=0
    for ts,kind,x in ev:
        k=(x.tk,x.entry)
        if kind==0:
            if len(held)>=maxpos: continue
            m=1.0
            if x.dist200==x.dist200 and x.dist200<0:
                m={'base':1.0,'half':0.5,'skip':0.0}[mode]
            if m==0: continue
            eqnow=cash+sum(held.values())
            amt=min(cash,eqnow*size*m)
            if amt<=0: continue
            cash-=amt; held[k]=amt; n+=1
        else:
            if k in held:
                cash+=held.pop(k)*(1+x.ret_pct/100-0.001)
        eqnow=cash+sum(held.values()); peak=max(peak,eqnow); mdd=min(mdd,eqnow/peak-1); curve.append((ts,eqnow))
    c=pd.Series(dict(curve)); c.index=pd.to_datetime(c.index)
    yrs=(c.index[-1]-c.index[0]).days/365.25
    return (c.iloc[-1]**(1/yrs)-1)*100, mdd*100, n, c
for name,df in (('lineup (10 live names)',tr[tr.tk.isin(lineup)]),('whole practice universe',tr)):
    print(name, 'trades', len(df))
    half=df.entry.iloc[len(df)//2]
    for mode in ('base','half','skip'):
        a,dd,n,c=sim(df,mode)
        a1,dd1,_,_=sim(df[df.entry<half],mode); a2,dd2,_,_=sim(df[df.entry>=half],mode)
        print(f"   {mode:5s}: {a:+6.1f}%/yr worst drop {dd:6.1f}% trades {n} | older half {a1:+.1f}%/yr ({dd1:.1f}%) | newer half {a2:+.1f}%/yr ({dd2:.1f}%)")
