import json, numpy as np, pandas as pd
S=json.load(open('/tmp/st_live.json'))
tr=pd.DataFrame(S['shadow_desk']['trades']).sort_values('entry')
tr['date']=tr.entry.str[:10]
d=pd.read_pickle('/tmp/r15/intraday.pkl').sort_values(['t','date'])
d['date']=d.date.astype(str)
g=d.groupby('t')
for c in ('press_last30','press_day'):
    d['prev_'+c]=g[c].shift(1)
d['prev_close_vs_vwap']=g['close'].shift(1)/g['vwap'].shift(1)-1
d['pre_vol_rel']=d.pre_vol/g['pre_vol'].transform(lambda s:s.shift(1).rolling(20).median())
d['ah_prev']=g['ah_px'].shift(1)/g['close'].shift(1)-1
d['gap']=d.open/d.prev_close-1
m=tr.merge(d[['t','date','prev_press_last30','prev_press_day','prev_close_vs_vwap','pre_vol_rel','ah_prev','gap']],left_on=['tk','date'],right_on=['t','date'],how='inner')
print('joined trades',len(m),'stocks',sorted(m.tk.unique()))
half=m.entry.iloc[len(m)//2]
def test(name,mask):
    out=[]
    for lab,part in (('older',m.entry<half),('newer',m.entry>=half)):
        a=m[part&mask].R; r=m[part&~mask].R
        diff=a.mean()-r.mean(); se=np.sqrt(a.var()/max(len(a),1)+r.var()/len(r))
        out.append(f"{lab}: n {len(a)} R {a.mean():+.3f} vs {r.mean():+.3f} (t {diff/se:+.1f})")
    print(f"{name:32s}",' | '.join(out))
test('prev last-30 selling (<-0.2)', m.prev_press_last30<-0.2)
test('prev last-30 buying (>0.2)', m.prev_press_last30>0.2)
test('prev day sold all day (<-0.1)', m.prev_press_day<-0.1)
test('prev close under VWAP -1%', m.prev_close_vs_vwap<-0.01)
test('pre-market vol 3x', m.pre_vol_rel>3)
test('after-hours prev down 2%+', m.ah_prev<-0.02)
test('gap down 2%+ today', m.gap<-0.02)
test('gap up 1%+ today', m.gap>0.01)
