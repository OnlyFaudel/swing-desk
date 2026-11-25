import json, numpy as np, pandas as pd
S=json.load(open('/tmp/st_live.json'))
tr=pd.DataFrame(S['shadow_desk']['trades']).sort_values('entry')
tr['d']=pd.to_datetime(tr.entry)
print('trades',len(tr),tr.entry.min(),tr.entry.max(),'avg R %.3f'%tr.R.mean())
half=tr.entry.iloc[len(tr)//2]; print('half split',half)
def test(name,mask):
    out=[]
    for lab,part in (('older',tr.entry<half),('newer',tr.entry>=half)):
        g=tr[part&mask].R; r=tr[part&~mask].R
        diff=g.mean()-r.mean(); se=np.sqrt(g.var()/len(g)+r.var()/len(r)) if len(g)>2 else np.nan
        out.append(f"{lab}: n {len(g)} R {g.mean():+.3f} vs rest {r.mean():+.3f} (diff {diff:+.3f}, t {diff/se:+.1f})")
    print(f"{name:28s}", ' | '.join(out))
test('vol_pct > 4', tr.vol_pct>4)
test('vol_pct > 3', tr.vol_pct>3)
test('open_fill', tr.open_fill==True)
test('weekday Wed', tr.weekday=='Wed')
test('group_up False', tr.group_up==False)
test('ret5d > 10', tr.ret5d_pct>10)
test('ret5d < -10', tr.ret5d_pct<-10)
test('group AI power', tr.group=='AI power')
test('tk BWXT', tr.tk=='BWXT')
test('dist_avg < -8', tr.dist_avg_pct<-8)
test('hour 15', tr.hour==15)
test('group_up F & ret5d<-5', (tr.group_up==False)&(tr.ret5d_pct<-5))
for g in tr.group.unique(): test('group '+g, tr.group==g)
# independent check of each notebook idea within nuclear only vs others
print('\n-- split by our nuclear names vs the rest (independent check)')
nuc=tr.group=='uranium/nuclear'
for nm,m in (('vol>4',tr.vol_pct>4),('open_fill',tr.open_fill==True),('Wed',tr.weekday=='Wed'),('group_up F',tr.group_up==False),('ret5d>10',tr.ret5d_pct>10)):
    for lab,sub in (('nuclear',nuc),('others',~nuc)):
        g=tr[sub&m].R; r=tr[sub&~m].R
        print(f"  {nm:10s} {lab:8s} n {len(g):4d} R {g.mean():+.3f} vs {r.mean():+.3f}")
