import sys; sys.path.insert(0,'/tmp/r20')
import importlib.util, pandas as pd, numpy as np
spec=importlib.util.spec_from_file_location('v','/tmp/r20/vol.py'); src=open('/tmp/r20/vol.py').read().split('def bw(C)')[0]
exec(src)
def up_on_dry_volume(C,H,L,V):   # 10-day rally of 8%+ while 10-day volume is 30%+ below the prior 50-day average
    return (C/C.shift(10)>1.08)&(V.rolling(10).mean()<0.7*V.shift(10).rolling(50).mean())
def down_on_dry_volume(C,H,L,V):  # 10-day drop of 8%+ on fading volume: sellers running out
    return (C/C.shift(10)<0.92)&(V.rolling(10).mean()<0.7*V.shift(10).rolling(50).mean())
def down_on_heavy_volume(C,H,L,V):
    return (C/C.shift(10)<0.92)&(V.rolling(10).mean()>1.5*V.shift(10).rolling(50).mean())
def quiet_volume_low(C,H,L,V):  # volume at a 6-month low while the stock is above its 50-day
    return (V.rolling(5).mean()<=V.rolling(5).mean().rolling(126).min()*1.05)&(C>C.rolling(50).mean())
for nm,f,H in (('rally on drying volume',up_on_dry_volume,10),('drop on drying volume',down_on_dry_volume,10),
               ('drop on heavy volume',down_on_heavy_volume,10),('volume 6-month low in uptrend',quiet_volume_low,20)):
    rep(nm,f,H)
