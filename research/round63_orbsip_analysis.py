import pandas as pd, numpy as np
t=pd.read_csv('/home/claude/swing-desk/data/orbsip/trades.csv').drop_duplicates(['day','sym'])
t['day']=pd.to_datetime(t.day); t['yr']=t.day.dt.year
t['era']=np.where(t.yr<=2018,'2016-18',np.where(t.yr<=2023,'2019-23','2024-26'))
t['risk']=0.10*t.atr/t.entry                      # stop distance as a fraction of entry
t['R']=t.ret/t.risk
COSTS={'no costs':lambda x:0*x.entry,
       "paper's ($0.0035/share each way)":lambda x:0.007/x.entry,
       'ours (1 tick + 0.1%)':lambda x:0.01/x.entry+0.001}
print(f"{len(t)} trades, {t.day.nunique()} days, {t.sym.nunique()} stocks; long {(t.side=='long').mean()*100:.0f}%; stopped in the entry minute {(t.reason=='stop_same_bar').mean()*100:.0f}%, stopped later {(t.reason=='stop').mean()*100:.0f}%, held to close {(t.reason=='close').mean()*100:.0f}%")
print(f"median stop distance {t.risk.median()*100:.2f}% of price; median relative volume {t.relvol.median():.1f}x\n")
print("Per trade, in R (1R = the stop distance) and %:")
for side in ('both','long'):
    x=t if side=='both' else t[t.side=='long']
    for cn,cf in COSTS.items():
        r=x.ret-cf(x); R=r/x.risk
        s=" | ".join(f"{e}: {R[x.era==e].mean():+.3f}R ({r[x.era==e].mean()*100:+.3f}%)" for e in ('2016-18','2019-23','2024-26'))
        print(f"  {side:4s} {cn:32s} {s}  win {(r>0).mean()*100:.0f}%")
def curve(x,cf,lev=4.0,risk=0.01):
    x=x.assign(net=x.ret-cf(x)); x['w']=risk/x.risk   # notional as a multiple of equity
    g=x.groupby('day')
    tot=g.w.sum(); scale=np.minimum(1,lev/tot)
    pnl=(x.w*x.net).groupby(x.day).sum()*scale
    days=pd.bdate_range(t.day.min(),t.day.max()); d=pnl.reindex(days).fillna(0)
    eq=(1+d).cumprod(); dd=(eq/eq.cummax()-1).min()
    return d,eq,dd
print("\nPortfolio (the paper's sizing: risk 1% of equity per trade, top 20 a day, leverage capped at 4x):")
for side in ('both','long'):
    x=t if side=='both' else t[t.side=='long']
    for cn,cf in COSTS.items():
        d,eq,dd=curve(x,cf)
        sh=d.mean()/d.std()*np.sqrt(252)
        e19=eq.loc[:'2023-12-31'].iloc[-1]
        yr=(1+d).groupby(d.index.year).prod()-1
        print(f"  {side:4s} {cn:32s} 2016-2023 {(e19-1)*100:+8.0f}%  all {(eq.iloc[-1]-1)*100:+9.0f}%  Sharpe {sh:4.2f}  worst drop {dd*100:5.1f}%")
        if cn.startswith('ours') or cn.startswith('paper'):
            print("       by year:", " ".join(f"{y}:{v*100:+.0f}%" for y,v in yr.items()))
