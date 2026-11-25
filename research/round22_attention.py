import json, pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
d=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']; spy=d['SPY']
def run(events, label, eras):
    e=pd.DataFrame(events); e['date']=pd.to_datetime(e.date); e=e[e.ticker.isin(d.columns)]
    cnt=e.groupby(['ticker','date']).size().rename('n').reset_index()
    rows=[]
    for t,g in cnt.groupby('ticker'):
        s=g.set_index('date').n
        bd=d[t].dropna(); 
        if len(bd)<300: continue
        daily=s.reindex(bd.index,fill_value=0)   # (events on non-trading days dropped)
        base=daily.rolling(60).mean().shift(1)
        quiet=daily.rolling(30).sum().shift(1)
        C=bd.values; S=spy.reindex(bd.index).values
        for i in range(61,len(bd)-21):
            spike=daily.iloc[i]>=max(3,4*base.iloc[i]) if base.iloc[i]==base.iloc[i] else False
            sil=quiet.iloc[i]==0 and daily.iloc[i]>=1
            if spike or sil:
                # enter next close, vs S&P, 5 and 20 days, 0.2% cost
                r5=C[i+6]/C[i+1]-S[i+6]/S[i+1]-0.002; r20=C[i+21]/C[i+1]-S[i+21]/S[i+1]-0.002
                rows.append((t,bd.index[i],'spike' if spike else 'first news after 30 quiet days',r5,r20))
    r=pd.DataFrame(rows,columns=['t','d','kind','r5','r20'])
    for k,g in r.groupby('kind'):
        out=[]
        for lab,(a,b) in eras.items():
            x=g[(g.d>=a)&(g.d<b)].copy()
            # one per stock per 20 days
            x=x.sort_values('d'); keep=[]; last={}
            for _,row in x.iterrows():
                if row.t not in last or (row.d-last[row.t]).days>28: keep.append(row); last[row.t]=row.d
            x=pd.DataFrame(keep)
            if len(x)==0: out.append(f"{lab}: none"); continue
            out.append(f"{lab}: 5d {x.r5.mean()*100:+.2f}% 20d {x.r20.mean()*100:+.2f}% (t {x.r20.mean()/x.r20.std()*np.sqrt(len(x)):+.1f}) n{len(x)}")
        print(f"{label} {k:34s}",' | '.join(out))
run(json.load(open('/home/claude/swing-desk/memory/archive_events.json')),'news ',{'19-22':('2019','2023'),'23-26':('2023','2027')})
run(json.load(open('/home/claude/swing-desk/memory/history_events.json')),'SEC  ',{'99-07':('1999','2008'),'08-18':('2008','2019'),'19-26':('2019','2027')})
