import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
d=pd.read_pickle('/tmp/sz/daily_max.pkl'); w=pd.read_pickle('/tmp/wide/wide.pkl')
def fields(df):
    return {f:df[f] for f in ('Open','High','Low','Close','Volume')}
A=fields(d); B=fields(w)
spy=(A['Close']['SPY'] if 'SPY' in A['Close'] else B['Close']['SPY']).dropna()
nuc_rel=[t for t in A['Close'].columns if t!='SPY']
wide=[t for t in B['Close'].columns if t not in nuc_rel and t!='SPY']
def events(F, tick, sig_fn, H):
    out=[]
    for t in tick:
        C=F['Close'][t].dropna()
        if len(C)<300: continue
        H_,L_,V=F['High'][t].reindex(C.index),F['Low'][t].reindex(C.index),F['Volume'][t].reindex(C.index)
        ok=(C>3)&((C*V).rolling(20).mean()>5e6)
        s=sig_fn(C,H_,L_,V)&ok
        idx=np.where(s.fillna(False).values)[0]; last=-999
        for i in idx:
            if i-last<H or i+1+H>=len(C): continue
            last=i; e,x=C.index[i+1],C.index[i+1+H]
            try: sp=spy.asof(x)/spy.asof(e)-1
            except Exception: continue
            out.append((e, C.iloc[i+1+H]/C.iloc[i+1]-1-sp-0.002))
    return pd.DataFrame(out,columns=['d','r'])
def rep(name,sig,H=10):
    row=[name,f'{H}d']
    for lab,F,tk in (('nuc+rel',A,nuc_rel),('wide',B,wide)):
        e=events(F,tk,sig,H)
        for era,m in (('08-18',(e.d>='2008')&(e.d<'2019')),('19-26',e.d>='2019')):
            r=e[m].r; row.append(f"{lab} {era}: {r.mean()*100:+.2f}% n{len(r)} t{r.mean()/r.std()*np.sqrt(len(r)) if len(r)>2 else 0:+.1f}")
        if 'wide'==lab:
            r=e[(e.d>='2000')&(e.d<'2007')].r
    print(' | '.join(row), flush=True)
def bw(C): m=C.rolling(20).mean(); s=C.rolling(20).std(); return (4*s/m), m+2*s, m-2*s
def squeeze_up(C,H,L,V):
    w,u,l=bw(C); low=w<=w.rolling(126).min()*1.1
    return low.shift(1) & (C>u)
def squeeze_dn(C,H,L,V):
    w,u,l=bw(C); low=w<=w.rolling(126).min()*1.1
    return low.shift(1) & (C<l)
def squeeze_only(C,H,L,V):
    w,u,l=bw(C); return w<=w.rolling(126).min()
def nr7_break(C,H,L,V):
    R=H-L; nr7=R<=R.rolling(7).min(); return nr7.shift(1) & (C>H.shift(1))
def nr7_break_trend(C,H,L,V):
    return nr7_break(C,H,L,V) & (C>C.rolling(50).mean())
def inside_break_dn(C,H,L,V):
    ins=(H<H.shift(1))&(L>L.shift(1)); return ins.shift(1)&(C<L.shift(1))
def low_vol_regime(C,H,L,V):
    v=C.pct_change().rolling(20).std(); return (v<v.rolling(252).quantile(0.2)) & (C>C.rolling(200).mean())
def vol_spike_own(C,H,L,V):  # stock's own 20d vol jumps to top 5% of its year while it is above 200d: fear in a leader
    v=C.pct_change().rolling(20).std(); return (v>v.rolling(252).quantile(0.95)) & (C>C.rolling(200).mean())
for nm,f,H in (('squeeze breakout up',squeeze_up,10),('squeeze breakout up',squeeze_up,20),('squeeze breakdown',squeeze_dn,10),
               ('tightest squeeze (no dir)',squeeze_only,20),('NR7 break up',nr7_break,5),('NR7 break up in uptrend',nr7_break_trend,5),
               ('inside-day breakdown',inside_break_dn,5),('calm uptrend (vol bottom 20%)',low_vol_regime,20),('vol spike in a leader',vol_spike_own,10)):
    rep(nm,f,H)
