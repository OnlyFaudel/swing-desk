import pickle, pandas as pd, numpy as np, warnings, json
from level_engine import prep, simulate, stats, daily_levels
warnings.filterwarnings("ignore")
B=pickle.load(open("bars.pkl","rb"))
H={t:prep(h) for t,h in B["h"].items()}; DL={t:daily_levels(B["d"][t]) for t in B["d"]}
spy=B["d"]["SPY"]; spy_ok={d.date():bool(c>m) for d,c,m in zip(spy.index,spy.Close,spy.Close.rolling(50).mean().shift())}
TRIOS={"CCJ+MU+PLTR":["CCJ","MU","PLTR"],"CCJ+TSM+ETN":["CCJ","TSM","ETN"]}
V={"baseline":{},
   "2+ touches":{"min_touches":2},"daily confluence":{"daily_confluence":True},"volume at level 1.5x":{"vol_mult":1.5},
   "ATR stop 1.0x":{"stop_mode":"atr","atr_mult":1.0},"ATR stop 1.5x":{"stop_mode":"atr","atr_mult":1.5},
   "breakeven at 1R":{"be_at_R":1.0},"half off at 1R":{"partial_at_R":1.0},"half off at 1.5R":{"partial_at_R":1.5},
   "trail 1R":{"trail_R":1.0},"trail 2R":{"trail_R":2.0},"skip 9:30 bar":{"skip_first_bar":True},
   "SPY above 50d":{"spy_filter":True},"hold 5 days":{"maxh":35},"order valid 2 days":{"valid":14},"rr 1.2":{"rr":1.2},"rr 2.0":{"rr":2.0}}
res={}
for vn,p in V.items():
    row={}
    for tn,tk in TRIOS.items():
        tr={"train":[],"test":[]}
        for t in tk:
            h=H[t]; mid=h.index[len(h)//2]
            for x in simulate(h,p,DL[t],spy_ok): tr["train" if x[0]<mid else "test"].append(x)
        row[tn]={k:stats(v) for k,v in tr.items()}
    res[vn]=row
    print(f"{vn:22s}", " | ".join(f"{tn}: train {row[tn]['train']['avg']:+.3f}% (n{row[tn]['train']['n']}) test {row[tn]['test']['avg']:+.3f}% (n{row[tn]['test']['n']}, t{row[tn]['test']['t']})" for tn in TRIOS))
json.dump(res,open("upgrade_study.json","w"),indent=1,default=float)
