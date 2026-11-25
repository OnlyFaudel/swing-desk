import pandas as pd, numpy as np, json
D=pd.read_pickle('/tmp/sz/daily_max.pkl'); C=D['Close']; spy=C['SPY']; idx=C.index; cost=0.002
cfg=json.load(open('/home/claude/swing-desk/config.json'))
NUC=["CCJ","NXE","UEC","DNN","UUUU","LEU","BWXT","CEG","VST","TLN"]; REL=[t for t in cfg['panic_rebound']['related_universe'] if t in C and t not in NUC]
rows=[]
for y in range(2008,2026):
    d=pd.Timestamp(y,11,1); tg=d+pd.Timedelta(days=(3-d.weekday())%7+21)
    tue=tg-pd.Timedelta(days=2); fri=tg+pd.Timedelta(days=1); mon=tg+pd.Timedelta(days=4)
    if tue not in idx or fri not in idx or mon not in idx: continue
    i0,i1,i2=idx.get_loc(tue),idx.get_loc(fri),idx.get_loc(mon)
    for lab,names in (('our 10',NUC),('related',REL)):
        g=lambda a,b:np.nanmean([(C[t].iloc[b]/C[t].iloc[a]-1) for t in names if np.isfinite(C[t].iloc[a]) and np.isfinite(C[t].iloc[b]) and C[t].iloc[a]>=3])-(spy.iloc[b]/spy.iloc[a]-1)
        rows.append(dict(yr=y,grp=lab,tue_fri=g(i0,i1)-cost,fri_mon=g(i1,i2),tue_mon=g(i0,i2)-cost))
R=pd.DataFrame(rows)
for (lab),x in R.groupby('grp'):
    for era,m in (('08-18',x.yr<=2018),('19-25',x.yr>=2019)):
        y=x[m]; f=lambda s:f'{s.mean()*100:+.2f}% (t {s.mean()/s.std()*np.sqrt(len(s)):.1f}, beat {int((s>0).sum())}/{len(s)})'
        print(f'EE {lab:7s} {era} | live Tue->Fri {f(y.tue_fri)} | extra Fri->Mon {f(y.fri_mon)} | Tue->Mon {f(y.tue_mon)}')
