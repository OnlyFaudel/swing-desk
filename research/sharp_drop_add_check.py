import pandas as pd, numpy as np
exec(open('/tmp/ideas/sd_entry.py').read().split("def run(")[0])
NUC=['CCJ','NXE','UEC','DNN','UUUU','LEU','BWXT','CEG','VST','TLN','OKLO','SMR','NNE','URG','LTBR','ASPI','GEV']
def second(add_pct, names):
    rows=[]
    for t in names:
        if t not in C: continue
        c=C[t]; v=V[t]
        if c.notna().sum()<300: continue
        r5=c/c.shift(5)-1; dv=(c*v).rolling(20).mean()
        sig=((r5<=-0.15)&(c>=3)&(dv>=5e6)).fillna(False).values
        i=25; n=len(c)
        while i<n-12:
            if not sig[i]: i+=1; continue
            e=c.iloc[i]; a_i=None; cst=e; x=None
            for k in range(i+1,min(i+11,n)):
                if a_i is None and c.iloc[k]<=e*(1-add_pct): a_i=k; cst=(e+c.iloc[k])/2
                if c.iloc[k]>=cst*1.10: x=c.iloc[k]; xi=k; break
            if x is None: xi=min(i+10,n-1); x=c.iloc[xi]
            if a_i is not None: rows.append(dict(yr=c.index[a_i].year, r=x/c.iloc[a_i]-1-cost, s=spy.iloc[xi]/spy.iloc[a_i]-1))
            i=xi+1
    R=pd.DataFrame(rows); out=[]
    for era,m in (('08-18',(R.yr>=2008)&(R.yr<=2018)),('19-26',R.yr>=2019)):
        d=R[m]; ex=d.r-d.s
        out.append(f"{era} n={len(d)} {d.r.mean()*100:+.2f}% vs S&P {ex.mean()*100:+.2f}% t {ex.mean()/ex.std()*np.sqrt(len(d)) if len(d)>2 else 0:.1f}")
    return " | ".join(out)
for p in (0.07,0.10,0.12,0.15): print(f'add after -{int(p*100)}% (all)      ', second(p,uni))
print('nuclear names only, -10%   ', second(0.10,[t for t in uni if t in NUC]))
print('related names only, -10%   ', second(0.10,[t for t in uni if t not in NUC]))
