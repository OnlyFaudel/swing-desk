import pandas as pd, numpy as np
I=pd.read_pickle('/tmp/r15/intraday.pkl'); I['date']=pd.to_datetime(I.date); I=I.sort_values(['t','date'])
I['nopen']=I.groupby('t').open.shift(-1); I['nclose']=I.groupby('t').close.shift(-1)
a=I[I.ah_px.notna()].copy(); a['ah']=a.ah_px/a.close-1
a['open_vs_4pm']=a.nopen/a.close-1   # did the next open keep any of the after-hours move?
a['vshare']=a.ah_vol/a.vol
print('after-hours volume as share of the day: median %.2f%%, 90th pct %.2f%%' % (a.vshare.median()*100, a.vshare.quantile(.9)*100))
for lab,m in (('AH up 3%+',a.ah>=0.03),('AH down 3%+',a.ah<=-0.03)):
    for vl,vm in (('any volume',a.vshare>=0),('real volume (>=1% of the day)',a.vshare>=0.01),('heavy (>=3% of the day)',a.vshare>=0.03)):
        x=a[m&vm]
        print(f'{lab:12s} {vl:32s} n={len(x):4d} | AH move avg {x.ah.mean()*100:+.2f}% | next open vs the 4 PM close {x.open_vs_4pm.mean()*100:+.2f}% (kept {x.open_vs_4pm.mean()/x.ah.mean()*100:.0f}% of the move) | next close vs AH price {(x.nclose/x.ah_px-1).mean()*100:+.2f}%')
# earnings nights specifically (biggest real after-hours events): use bots' earnings dates file
import json
E=json.load(open('/home/claude/swing-desk/research/event_history.json'))
ed={(t,pd.Timestamp(d)) for t,v in E.items() for d,_ in v.get('earnings_moves_pct',[])}
a['earn']=[((r.t,r.date) in ed) or ((r.t,r.date+pd.Timedelta(days=1)) in ed) for r in a.itertuples()]
x=a[(a.ah.abs()>=0.03)&a.earn]; print('earnings nights with 3%+ AH move:',len(x),'| next open kept %.0f%% of the AH move' % (x.open_vs_4pm.mean()/x.ah.mean()*100 if len(x) else float('nan')))
