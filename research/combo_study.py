import pickle, numpy as np, warnings, json
from level_engine import prep, simulate, stats, daily_levels
warnings.filterwarnings("ignore")
B=pickle.load(open("bars.pkl","rb")); H={t:prep(h) for t,h in B["h"].items()}; DL={t:daily_levels(B["d"][t]) for t in B["d"]}
TRIOS={"CCJ+MU+PLTR":["CCJ","MU","PLTR"],"CCJ+TSM+ETN":["CCJ","TSM","ETN"]}
V={"valid 2d":{"valid":14},"valid 2d + skip 9:30":{"valid":14,"skip_first_bar":True},"valid 2d + hold 5d":{"valid":14,"maxh":35},
   "valid 2d + ATR stop 1x":{"valid":14,"stop_mode":"atr","atr_mult":1.0},"valid 2d + breakeven 1R":{"valid":14,"be_at_R":1.0},
   "valid 2d + skip 9:30 + hold 5d":{"valid":14,"skip_first_bar":True,"maxh":35},"valid 3d":{"valid":21}}
for vn,p in V.items():
    out=[]
    for tn,tk in TRIOS.items():
        tr={"train":[],"test":[]}
        for t in tk:
            h=H[t]; mid=h.index[len(h)//2]
            for x in simulate(h,p,DL[t]): tr["train" if x[0]<mid else "test"].append(x)
        a,b=stats(tr["train"]),stats(tr["test"]); out.append(f"{tn}: train {a['avg']:+.3f} test {b['avg']:+.3f} (n{b['n']}, t{b['t']}, win {b['win']}%)")
    print(f"{vn:32s}"," | ".join(out))
# per-ticker under chosen variant, and costs sensitivity
best={"valid":14,"skip_first_bar":True}
print("\nchosen = valid 2d + skip 9:30, per ticker (train / test):")
for t in ["CCJ","MU","PLTR","TSM","ETN"]:
    h=H[t]; mid=h.index[len(h)//2]; xs=simulate(h,best,DL[t])
    print(f"  {t}: {stats([x for x in xs if x[0]<mid])['avg']:+.3f} / {stats([x for x in xs if x[0]>=mid])['avg']:+.3f}")
for c in [0.1,0.2,0.3]:
    xs=[x for t in ["CCJ","TSM","ETN"] for x in simulate(H[t],{**best,"cost_rt":c},DL[t])]
    print(f"  CCJ+TSM+ETN full 2y at {c}% round-trip cost: {stats(xs)}")
