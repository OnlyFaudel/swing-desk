import sys, pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
src=open('/tmp/r20/vol.py').read().split('def bw(C)')[0]; exec(src)
# 1-2 all-time high distance (uses full history since listing in the data; skip first 2 years of each stock)
def ath_new(C,H,L,V):   # first close at a new all-time high after 60+ days without one
    m=C.cummax(); new=C>=m; age=C.expanding().count()>500
    return new & ~(new.shift(1).rolling(60).max().astype(bool)) & age
def near_ath(C,H,L,V):  # within 3% of all-time high
    return (C>=C.cummax()*0.97)&(C.expanding().count()>500)
def deep_off_ath(C,H,L,V):  # 70%+ below all-time high and above its 50-day (a fallen stock turning)
    return (C<=C.cummax()*0.30)&(C>C.rolling(50).mean())&(C.shift(1)<=C.rolling(50).mean().shift(1))&(C.expanding().count()>500)
# 3-4 round numbers
def lvl(C):
    return np.where(C<20,5,np.where(C<100,10,np.where(C<500,50,100)))
def cross_round_up(C,H,L,V):  # close crosses above a round number (5/10/50/100 grid by price) for the first time in 60 days
    g=pd.Series(lvl(C),index=C.index); k=np.floor(C/g); 
    up=(k>k.shift(1)); first=up & (C.shift(1).rolling(60).max()<k*g)
    return first
def just_under_round(C,H,L,V):  # closes within 1.5% under a round number after rising into it
    g=pd.Series(lvl(C),index=C.index); nxt=(np.floor(C/g)+1)*g
    return (C>=nxt*0.985)&(C/C.shift(10)>1.05)
# 5 anniversary: the day one year after a 15%+ one-day crash
def crash_anniv(C,H,L,V):
    r=C.pct_change(); crash=(r<=-0.15).astype(float)
    return crash.shift(252).fillna(0)>0
for nm,f,H in (('new all-time high after 60d',ath_new,20),('within 3% of all-time high',near_ath,20),
               ('70%+ off ATH, first close over 50d',deep_off_ath,20),('first cross above a round number',cross_round_up,10),
               ('just under a round number after a run',just_under_round,10),('1-year anniversary of a 15% crash',crash_anniv,10)):
    rep(nm,f,H)
