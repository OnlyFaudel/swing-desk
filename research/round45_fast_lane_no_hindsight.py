import pandas as pd, numpy as np
I=pd.read_pickle('/tmp/r41/intraday.pkl'); I['date']=pd.to_datetime(I.date); I=I.sort_values(['t','date'])
D=pd.read_pickle('/tmp/sz/daily_max.pkl'); C=D['Close']; spy=C['SPY']
g=I.groupby('t'); I['pc']=g.close.shift(1); I['v15avg']=g.vol15.transform(lambda s:s.shift(1).rolling(20).median())
rows=[]
for r in I.itertuples():
    if r.t not in C or r.date not in C.index or not r.pc or r.pc!=r.pc: continue
    i=C.index.get_loc(r.date)
    if i+21>=len(C): continue
    for buy,px in (('9:45',r.px945),('10:00',r.px1000)):
        if not px or px!=px: continue
        up=px/r.pc-1; vr=r.vol15/r.v15avg if r.v15avg else np.nan
        if up<0.05 or not(vr>=3): continue      # known at buy time: up 5%+ vs yesterday, first-15-min volume 3x normal
        sp=lambda b: spy.iloc[b]/spy.iloc[i-1]-1   # S&P from yesterday's close (its gap is in there too)
        spd=spy.iloc[i]/spy.iloc[i-1]-1
        rows.append(dict(d=r.date,t=r.t,buy=buy,up=up,gap=r.open/r.pc-1,spy_day=spd,
            to_close=C[r.t].iloc[i]/px-1-0.002, next_close=C[r.t].iloc[i+1]/px-1-(spy.iloc[i+1]/spy.iloc[i]-1)-0.002,
            d5=C[r.t].iloc[i+5]/px-1-(spy.iloc[i+5]/spy.iloc[i]-1)-0.002, d20=C[r.t].iloc[i+20]/px-1-(spy.iloc[i+20]/spy.iloc[i]-1)-0.002))
x=pd.DataFrame(rows); x=x[x.spy_day<0.02]
# one per stock per 10 days
x=x.sort_values('d'); keep=[]; last={}
for _,r in x.iterrows():
    k=(r.t,r.buy)
    if k not in last or (r.d-last[k]).days>14: keep.append(r); last[k]=r.d
x=pd.DataFrame(keep)
for per,(a,b) in {'2016-18':('2016','2019'),'2019-26':('2019','2027')}.items():
    for buy in ('9:45','10:00'):
        y=x[(x.d>=a)&(x.d<b)&(x.buy==buy)]
        t=lambda s: s.mean()/s.std()*np.sqrt(len(s))
        print(f"{per} buy {buy}: n {len(y):3d} | already up {y.up.mean()*100:+.1f}% | rest of day {y.to_close.mean()*100:+.2f}% (t {t(y.to_close):+.1f}) | next close {y.next_close.mean()*100:+.2f}% | 5d {y.d5.mean()*100:+.2f}% (t {t(y.d5):+.1f}) | 20d {y.d20.mean()*100:+.2f}% (t {t(y.d20):+.1f}) | worst 5% 5d {y.d5.quantile(.05)*100:.1f}%")
x.to_pickle('/tmp/r45b.pkl')
D=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']
tk=sorted(set(x.t))
ex20=pd.concat([(D[t].shift(-20)/D[t]-1)-(D['SPY'].shift(-20)/D['SPY']-1) for t in tk],axis=1)
ex20.columns=tk
for per,(a,b) in {'2016-18':('2016','2019'),'2019-26':('2019','2027')}.items():
    base=ex20[(ex20.index>=a)&(ex20.index<b)].stack().mean()
    y=x[(x.d>=a)&(x.d<b)&(x.buy=='9:45')]
    # matched baseline: same stocks, same months
    mb=np.mean([ex20[t][(ex20.index.year==d.year)&(ex20.index.month==d.month)].mean() for d,t in zip(y.d,y.t)])
    print(f"{per}: any-day 20d excess for these stocks {base*100:+.2f}% | same stock & month baseline {mb*100:+.2f}% | fast-lane 20d {y.d20.mean()*100:+.2f}% -> edge {(y.d20.mean()-mb)*100:+.2f}%")
