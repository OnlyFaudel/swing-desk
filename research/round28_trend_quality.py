import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
src=open('/tmp/r20/vol.py').read().split('def bw(C)')[0]; exec(src)
def smooth_rally(C,H,L,V):
    r=C.pct_change(); up=(r>0).rolling(20).mean(); return (C/C.shift(20)>1.15)&(up>=0.65)
def choppy_rally(C,H,L,V):
    r=C.pct_change(); up=(r>0).rolling(20).mean(); return (C/C.shift(20)>1.15)&(up<=0.50)
def smooth_decline(C,H,L,V):
    r=C.pct_change(); up=(r>0).rolling(20).mean(); return (C/C.shift(20)<0.85)&(up<=0.35)
def choppy_decline(C,H,L,V):
    r=C.pct_change(); up=(r>0).rolling(20).mean(); return (C/C.shift(20)<0.85)&(up>=0.50)
for nm,f,H in (('smooth rally (15%+, 65%+ up days)',smooth_rally,20),('choppy rally (15%+, <=50% up days)',choppy_rally,20),
               ('smooth decline (-15%, <=35% up days)',smooth_decline,20),('choppy decline (-15%, 50%+ up days)',choppy_decline,20)):
    rep(nm,f,H)
