import pandas as pd, numpy as np, json, warnings; warnings.filterwarnings("ignore")
W=pd.read_pickle('wide.pkl'); O,C=W['Open'],W['Close']
N=pd.read_pickle('/tmp/sz/daily_max.pkl')
for t in N['Close'].columns:
    if t not in C.columns and 'Open' in N.columns.get_level_values(0): O[t]=N['Open'][t]; C[t]=N['Close'][t]
NUC=["CCJ","NXE","UEC","DNN","UUUU","LEU","BWXT","CEG","VST","TLN"]
REL=json.load(open('/tmp/cfg.json'))['panic_rebound']['related_universe']
U=[t for t in NUC+REL if t in C.columns]
spy_gap=O['SPY']/C['SPY'].shift()-1; spy_day=C['SPY']/C['SPY'].shift()-1
cost=0.002
for thr in (0.015,0.02):
    days=spy_gap[spy_gap<=-thr].index
    rows=[]
    for d in days:
        i=C.index.get_loc(d)
        if i+6>=len(C): continue
        for t in U:
            o,pc=O[t].iloc[i],C[t].iloc[i-1]
            if np.isnan(o) or np.isnan(pc) or o/pc-1>-0.03: continue
            c0,c5=C[t].iloc[i],C[t].iloc[i+5]
            if np.isnan(c0) or np.isnan(c5): continue
            rows.append(dict(d=d,t=t,nuc=t in NUC,oc=c0/o-1-cost, o5=c5/o-1-cost, c5=c5/c0-1-cost, spy_oc=C['SPY'].iloc[i]/O['SPY'].iloc[i]-1, spy_o5=C['SPY'].iloc[i+5]/O['SPY'].iloc[i]-1, spy_closed_panic=spy_day.iloc[i]<=-0.02))
    df=pd.DataFrame(rows); df['era']=np.where(df.d<'2019-01-01','2008-18','2019-26'); df=df[df.d>='2008-01-01']
    print(f"\nS&P opens down {thr*100:.1f}%+ : {df.d.nunique()} days, {len(df)} stock buys (stock also opened down 3%+), costs 0.2%")
    g=df.groupby('era')
    out=pd.DataFrame({'days':g.d.nunique(),'buys':g.size(),
      'buy open, sell close %':g.oc.mean()*100,'beat S&P same day %':(g.apply(lambda x:(x.oc-x.spy_oc).mean()))*100,
      'buy open, sell 5d %':g.o5.mean()*100,'beat S&P 5d %':(g.apply(lambda x:(x.o5-x.spy_o5).mean()))*100,
      'win 5d %':g.apply(lambda x:(x.o5>0).mean())*100})
    print(out.round(2).to_string())
    # per-day average (clustering)
    pd_=df.groupby(['era','d']).agg(o5=('o5','mean'),x=('spy_o5','mean')).reset_index()
    print("  per-day avg 5d (each day counted once):", pd_.groupby('era').o5.mean().mul(100).round(2).to_dict(), " | days S&P recovered above -2% by close:", round((~df.drop_duplicates('d').spy_closed_panic).mean()*100),"%")
    worst=pd_.sort_values('o5').head(4); print("  worst days:", [(str(r.d.date()),round(r.o5*100,1)) for r in worst.itertuples()])
print("\nExcluding Feb-Apr 2020 (2% gap version):")
x=df[~((df.d>='2020-02-15')&(df.d<='2020-04-30'))]
pdx=x.groupby(['era','d']).agg(o5=('o5','mean'),s=('spy_o5','mean')).reset_index()
print(pdx.groupby('era').agg(days=('d','size'),avg5=('o5','mean'),vs_spy=('s',lambda s:0)).assign(avg5=lambda z:z.avg5*100).round(2).to_string())
print("beat S&P per day:", (pdx.o5-pdx.s).groupby(pdx.era).mean().mul(100).round(2).to_dict())
