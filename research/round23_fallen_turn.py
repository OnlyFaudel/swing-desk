import pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
src=open('/tmp/r20/vol.py').read().split('def bw(C)')[0]; exec(src)
def make(off,need_cross=True):
    def f(C,H,L,V):
        s=(C<=C.cummax()*off)&(C>C.rolling(50).mean())&(C.expanding().count()>500)
        if need_cross: s=s&(C.shift(1)<=C.rolling(50).mean().shift(1))
        return s
    return f
for nm,f,H in (('70% off ATH, cross 50d',make(0.30),40),('80% off ATH, cross 50d',make(0.20),20),('50% off ATH, cross 50d',make(0.50),20)):
    rep(nm,f,H)
# 2000-06 era for the nuclear/related set
def era00(f,H):
    e=events(A,nuc_rel,f,H); r=e[(e.d>='2000')&(e.d<'2007')].r
    print('  2000-06 nuc+rel', f"{r.mean()*100:+.2f}% n{len(r)}")
era00(make(0.30),20)
