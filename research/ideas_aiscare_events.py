exec(open('/tmp/ideas2/run.py').read().split('# 1. sympathy')[0])
def events(names,n,gap=10):
    out=[]; last=-99
    for i in np.where((nv<=-0.06).values)[0]:
        if i+n>=len(C) or i-last<gap: continue
        xs=[fwd(t,i,n) for t in names if t in C and ok[t].iloc[i]]
        xs=[x for x in xs if x==x]
        if xs: out.append((C.index[i],np.mean(xs))); last=i
    return pd.Series(dict(out))
for lab,names in (('power trio + NRG',['CEG','VST','TLN','NRG']),('other utilities (independent check)',['PEG','ETR','XLU','NEE','D','SO','DUK','AEP','EXC']),('lineup',['CCJ','NXE','UEC','DNN','UUUU','LEU','BWXT','CEG','VST','TLN'])):
    for n in (5,10):
        s=events(names,n)
        a,b=s[s.index.year<=2018],s[s.index.year>=2019]
        f=lambda y:f'{y.mean()*100:+.2f}% (t {y.mean()/y.std()*np.sqrt(len(y)):.1f}, n {len(y)}, up {(y>0).mean()*100:.0f}%)' if len(y)>2 else 'n<3'
        print(f'{lab:36s} {n:2d}d one per scare day: 2008-18 {f(a)} | 2019-26 {f(b)}')
s=events(['CEG','VST','TLN','NRG'],10); print(s.groupby(s.index.year).agg(['count','mean']).assign(mean=lambda x:(x['mean']*100).round(1)).T.to_string())
