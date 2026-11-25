import yfinance as yf, pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
cases=[
 ('Dot-com (Cisco scare -> network/chip suppliers)','CSCO',['JNPR','CIEN','ORCL','QCOM','AMAT','INTC','TXN','ADI','KLAC','LRCX'],'1998-01-01','2002-12-31',-0.06),
 ('EVs (Tesla scare -> lithium/battery/charging)','TSLA',['ALB','SQM','PLUG','BLNK','LIT'],'2019-06-01','2023-06-30',-0.06),
 ('Crypto (bitcoin scare -> miners/proxies)','BTC-USD',['RIOT','MARA','MSTR'],'2017-01-01','2022-12-31',-0.10),
 ('AI (NVIDIA scare -> power trio), for comparison','NVDA',['CEG','VST','TLN'],'2023-01-01','2026-11-24',-0.06),
]
for name,lead,basket,a,b,th in cases:
    px=yf.download([lead]+basket+['SPY'],start=a,end=b,progress=False,auto_adjust=True)['Close']
    L=px[lead].dropna(); spy=px['SPY'].ffill()
    tr=px.index.intersection(spy.dropna().index)
    lr=L.pct_change().reindex(tr)     # crypto trades weekends: use the leader's move into each stock-market close
    if lead=='BTC-USD': lr=(L.reindex(pd.date_range(L.index[0],L.index[-1])).ffill()).reindex(tr).pct_change()
    B=px[basket].reindex(tr)
    H=10
    fwd=(B.shift(-H)/B-1).mean(axis=1)-(spy.reindex(tr).shift(-H)/spy.reindex(tr)-1)-0.002
    days=lr[lr<=th].index; pick=[]; last=None
    for d in days:
        i=tr.get_loc(d)
        if last is None or i-last>=H: pick.append(d); last=i
    v=fwd.reindex(pick).dropna(); base=fwd.dropna()
    up=(v>0).mean()*100 if len(v) else 0
    t=(v.mean()-base.mean())/(v.std()/np.sqrt(len(v))) if len(v)>2 else float('nan')
    print(f"{name}\n   scare days {len(v)} | basket next 10 days vs S&P {v.mean()*100:+.2f}% (up {up:.0f}% of the time) | any day in the boom {base.mean()*100:+.2f}% | edge {(v.mean()-base.mean())*100:+.2f}% (t {t:+.1f})")
    if len(v): print('   by year:', ' '.join(f"{y}: {g.mean()*100:+.1f}% ({len(g)})" for y,g in v.groupby(v.index.year)))
