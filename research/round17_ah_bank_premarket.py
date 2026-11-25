import pandas as pd, numpy as np
I=pd.read_pickle('/tmp/r15/intraday.pkl'); I['date']=pd.to_datetime(I.date); I=I.sort_values(['t','date'])
for c in ('open','px935','close','pre_px','prev'): pass
I['prev']=I.groupby('t').close.shift(1); I['nopen']=I.groupby('t').open.shift(-1); I['n935']=I.groupby('t').px935.shift(-1); I['nclose']=I.groupby('t').close.shift(-1); I['npre']=I.groupby('t').pre_px.shift(-1)
def era(df,col,label):
    out=[]
    for e,m in (('2016-18',df.date.dt.year<=2018),('2019-26',df.date.dt.year>=2019)):
        y=df[m][col].dropna(); out.append(f'{e} n={len(y):3d} {y.mean()*100:+.2f}% (t {y.mean()/y.std()*np.sqrt(len(y)) if len(y)>2 else 0:.1f}, up {(y>0).mean()*100:.0f}%)')
    print(f'{label:62s} '+' | '.join(out))
a=I[I.ah_px.notna()].copy(); a['ah']=a.ah_px/a.close-1; a['vs']=a.ah_vol/a.vol
up=a[(a.ah>=0.03)&(a.vs>=0.01)].copy()
# MIRROR: a held position sells at the after-hours price, buys back at the next close (vs simply holding): gain = AH price / next close - 1 - 1% cost
up['bank_close']=up.ah_px/up.nclose-1-0.01; up['bank_935']=up.ah_px/up.n935-1-0.01
era(up,'bank_close','1 AH jump 3%+: sell AH, buy back next close (vs holding)')
era(up,'bank_935','1 AH jump 3%+: sell AH, buy back 9:35 (vs holding)')
era(up[up.ah>=0.05],'bank_close','1 AH jump 5%+: sell AH, buy back next close')
# PRE-MARKET: pre-market price vs the previous close; buy the pre-market dip, sell 9:35 / close same day
p=I[I.pre_px.notna()&I.prev.notna()].copy(); p['pm']=p.pre_px/p.prev-1
for thr in (0.03,0.05):
    d=p[p.pm<=-thr].copy(); d['to935']=d.px935/d.pre_px-1-0.01; d['toclose']=d.close/d.pre_px-1-0.01; d['open_vs_pre']=d.open/d.pre_px-1
    era(d,'to935',f'2 pre-market down {int(thr*100)}%+: buy pre-market, sell 9:35')
    era(d,'toclose',f'2 pre-market down {int(thr*100)}%+: buy pre-market, sell close')
    u=p[p.pm>=thr].copy(); u['to935']=u.pre_px/u.px935-1-0.01
    era(u,'to935',f'2 pre-market UP {int(thr*100)}%+: (as held) sell pre-market vs 9:35')
