import pandas as pd, numpy as np, warnings; warnings.filterwarnings("ignore")
I=pd.read_pickle('/tmp/r41/intraday.pkl'); I['date']=pd.to_datetime(I.date); I=I.sort_values(['t','date'])
I['pc']=I.groupby('t').close.shift(); I['prev_close']=I.prev_close.fillna(I.pc)
I['n935']=I.groupby('t').px935.shift(-1)
I=I.dropna(subset=['prev_close','open','px935','px1000','px1530','close'])
I=I[(I.vol*I.close>3e6)]
I['cost']=0.01/I.close+0.0010          # one tick of spread + 0.1% slippage/fees, round trip
I['era']=np.where(I.date.dt.year<=2018,'2016-18','2019-26')
I['gap']=I.open/I.prev_close-1
def test(name,mask,entry,exit_,note=''):
    x=I[mask].copy()
    x['r']=x[exit_] /x[entry]-1-x.cost if isinstance(exit_,str) else exit_(x)/x[entry]-1-x.cost
    base=I.copy(); base['r']=(base[exit_] if isinstance(exit_,str) else exit_(base))/base[entry]-1-base.cost
    out=[]
    for e in ('2016-18','2019-26'):
        g=x[x.era==e]; b=base[base.era==e]
        if len(g)<5: out.append(f"{e}: n {len(g)}"); continue
        d=g.groupby('date').r.mean(); t=d.mean()/(d.std()/np.sqrt(len(d)))
        out.append(f"{e}: {g.r.mean()*100:+.2f}%/trade (n {len(g)}, {len(d)} days, t {t:.1f}, win {(g.r>0).mean()*100:.0f}%) | same window any day {b.r.mean()*100:+.2f}%")
    print(f"{name}{note}\n   "+"\n   ".join(out),flush=True)
print("All long-only (a $1k account can't short). Costs: 1 tick spread + 0.1% per round trip.\n")
test("1. Gap-down fill: opens 2%+ down, buy 9:35, sell at the close", I.gap<=-0.02,'px935','close')
test("1b. Gap-down fill, deep: opens 4%+ down, buy 9:35, sell close", I.gap<=-0.04,'px935','close')
fill=lambda x: np.where((x.high>=x.prev_close)&(x.high_min>5),x.prev_close,x.close)
test("1c. Gap-down 2%+, buy 9:35, sell at yesterday's close if reached, else close", I.gap<=-0.02,'px935',fill)
test("2. Gap-and-go: opens 3%+ up and still rising at 9:35, buy 9:35, sell close", (I.gap>=0.03)&(I.px935>I.open),'px935','close')
test("3. Morning momentum: up 1%+ from the open by 10:00, buy 10:00, sell close", I.px1000>=I.open*1.01,'px1000','close')
test("4. Morning dip: down 3%+ from the open by 10:00, buy 10:00, sell close", I.px1000<=I.open*0.97,'px1000','close')
test("5. Strong buying in first 30 min (top 10% pressure), buy 10:00, sell close", I.press30>=I.press30.quantile(0.9),'px1000','close')
test("6. Intraday momentum (academic): up since yesterday's close at 10:00, buy 3:30, sell close", I.px1000>I.prev_close,'px1530','close')
test("6b. Same but down at 10:00 (should be weak), buy 3:30, sell close", I.px1000<I.prev_close,'px1530','close')
test("7. Late selloff: down 3%+ on the day at 3:30, buy 3:30, sell close", I.px1530<=I.prev_close*0.97,'px1530','close')
test("7b. Late selloff overnight: down 3%+ at 3:30, buy 3:30, sell 9:35 next day (not a day trade)", I.px1530<=I.prev_close*0.97,'px1530','n935')
test("8. Opening drive fade: up 3%+ at 9:45 vs yesterday, buy... no: wait for pullback, buy 10:00 if below 9:45", (I.px945>=I.prev_close*1.03)&(I.px1000<I.px945),'px1000','close')
test("9. Big morning range then calm: day low hit in first 15 min and 10:00 above the open, buy 10:00, sell close", (I.low_min<=15)&(I.px1000>I.open),'px1000','close')
