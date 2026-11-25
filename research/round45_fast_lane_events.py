import pandas as pd, numpy as np
I=pd.read_pickle('/tmp/r41/intraday.pkl'); I['date']=pd.to_datetime(I.date); I=I.set_index(['t','date']).sort_index()
D=pd.read_pickle('/tmp/sz/daily_max.pkl'); C=D['Close']; V=D['Volume']; spy=C['SPY']
deals=[('2024-03-04','TLN'),('2024-09-20','CEG'),('2025-06-03','CEG'),('2025-06-11','TLN'),('2026-01-09','VST'),('2026-09-30','CEG'),('2026-10-06','CEG')]
lic=[('2026-03-04',t) for t in ['OKLO','SMR','NNE','LEU','CCJ','BWXT','CEG']]+[('2026-11-09',t) for t in ['OKLO','SMR','NNE','LEU','CCJ','BWXT','CEG']]
ev=[(pd.Timestamp(d),t,'deal') for d,t in deals]+[(pd.Timestamp(d),t,'NRC approval') for d,t in lic]
# stock-specific pops: +8% day on 2x volume with the S&P under +2%
R=C.pct_change(); Sr=spy.pct_change(); va=V.rolling(20).mean().shift(1)
for t in I.index.get_level_values(0).unique():
    if t not in C: continue
    m=(R[t]>=0.08)&(V[t]>=2*va[t])&(Sr<0.02)
    last=None
    for d in m[m].index:
        if d<pd.Timestamp('2016-01-01'): continue
        if last is not None and (d-last).days<10: continue
        last=d; ev.append((d,t,'pop 8%+ on 2x volume'))
rows=[]
for d,t,kind in ev:
    if (t,d) not in I.index or t not in C or d not in C.index: continue
    r=I.loc[(t,d)]; i=C.index.get_loc(d)
    if i+21>=len(C) or i<1: continue
    pc=C[t].iloc[i-1]; gap=r.open/pc-1; day=C[t].iloc[i]/pc-1
    sp=lambda a,b: spy.iloc[b]/spy.iloc[a]-1
    for buy in ('px935','px945','px1000'):
        px=r[buy]
        if not px or px!=px: continue
        # S&P from ~open: approximate with prev close->horizon (S&P intraday not stored); subtract S&P over the same days
        out=dict(d=d,t=t,kind=kind,buy=buy,gap_news=gap>=0.04,day_move=day,left_at_buy=(C[t].iloc[i]/px-1)/day if day>0 else np.nan,
                 to_close=C[t].iloc[i]/px-1-0.002, next_close=C[t].iloc[i+1]/px-1-sp(i,i+1)-0.002,
                 d5=C[t].iloc[i+5]/px-1-sp(i,i+5)-0.002, d20=C[t].iloc[i+20]/px-1-sp(i,i+20)-0.002)
        rows.append(out)
x=pd.DataFrame(rows)
print('events with minute data:',x[x.buy=='px935'].groupby('kind').size().to_dict())
pd.set_option('display.width',220)
for kind,g in x.groupby('kind'):
    for per,(a,b) in {'2016-18':('2016','2019'),'2019-26':('2019','2027')}.items():
        y=g[(g.d>=a)&(g.d<b)]
        if len(y)==0: continue
        for buy in ('px935','px945','px1000'):
            z=y[y.buy==buy]
            for gn,zz in z.groupby('gap_news'):
                print(f"{kind:22s} {per} buy@{buy[2:]:4s} {'gap (news before open)' if gn else 'during the day     '} n{len(zz):3d} | day move {zz.day_move.mean()*100:+5.1f}% | to close {zz.to_close.mean()*100:+.2f}% | next close {zz.next_close.mean()*100:+.2f}% | 5d {zz.d5.mean()*100:+.2f}% | 20d {zz.d20.mean()*100:+.2f}%")
x.to_pickle('/tmp/r45.pkl')
