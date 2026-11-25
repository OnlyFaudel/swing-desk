import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
d=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']; w=pd.read_pickle('/tmp/wide/wide.pkl')['Close']
allp=pd.concat([d,w[[c for c in w.columns if c not in d.columns]]],axis=1).sort_index(); spy=allp['SPY']
groups={'ours':['CCJ','UEC','DNN','UUUU','NXE','LEU','BWXT','CEG','VST','TLN'],
 'semis':['NVDA','AMD','AVGO','MU','TSM','QCOM','TXN','INTC','AMAT','LRCX','KLAC','ADI'],
 'banks':['JPM','BAC','WFC','C','GS','MS','USB','PNC'],'energy':['XOM','CVX','COP','SLB','EOG','OXY','HAL','MPC'],
 'megatech':['AAPL','MSFT','AMZN','GOOGL','META','NFLX','ADBE','CRM']}
H=20
for g,ts in groups.items():
    p=allp[[t for t in ts if t in allp]]; p=p[p.index>='1999']; R=p.pct_change()
    B=(1+R.mean(axis=1)).cumprod(); dd=B/B.rolling(60).max()-1; above=B>B.rolling(20).mean()
    trig=(dd.shift(1).rolling(10).min()<=-0.15)&above&~above.shift(1).fillna(False)
    rows=[];last=None
    for x in trig[trig].index:
        if last is not None and (x-last).days<40: continue
        last=x; i=p.index.get_loc(x)
        if i+H>=len(p): continue
        win=p.iloc[max(0,i-60):i+1]; sdd=(win.iloc[-1]/win.max()-1).dropna()
        if len(sdd)<4: continue
        strong=sdd.nlargest(2).index; weak=sdd.nsmallest(2).index
        fr=p.iloc[i+H]/p.iloc[i]-1-(spy.iloc[i+H]/spy.iloc[i]-1) if False else p.iloc[i+H]/p.iloc[i]-1-(spy.asof(p.index[i+H])/spy.asof(p.index[i])-1)
        rows.append((x,fr[strong].mean()-0.002,fr[weak].mean()-0.002,fr.dropna().mean()-0.002))
    r=pd.DataFrame(rows,columns=['d','held_up','fell_most','group'])
    out=[]
    for era,(a,b) in {'00-07':('2000','2008'),'08-18':('2008','2019'),'19-26':('2019','2027')}.items():
        x=r[(r.d>=a)&(r.d<b)]
        if len(x): out.append(f"{era}: held-up best {x.held_up.mean()*100:+.2f}% | fell most {x.fell_most.mean()*100:+.2f}% | group {x.group.mean()*100:+.2f}% n{len(x)}")
    print(f"{g:9s}",' || '.join(out))
