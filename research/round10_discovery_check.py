import pandas as pd, numpy as np, json
D=pd.read_pickle('/tmp/sz/daily_max.pkl'); D=D[D.index>='2007-01-01']; C,V=D['Close'],D['Volume']; spy=C['SPY']; cost=0.002
NUC=["CCJ","NXE","UEC","DNN","UUUU","LEU","BWXT","CEG","VST","TLN"]; MIN=["CCJ","NXE","UEC","DNN","UUUU"]
bk=C[NUC].pct_change().mean(axis=1).fillna(0); bkc=(1+bk).cumprod()
dv=(C*V).rolling(20).mean(); hi=C.rolling(252).max(); lo=C.rolling(252).min()
def test(names,cond,label,n=5,vs='spy',gap=5):
    rows=[]
    for t in names:
        c=C[t]; s=cond(t).fillna(False).values; last=-99
        for i in np.where(s)[0]:
            if i<260 or i+n>=len(c) or i-last<gap or not (c.iloc[i]>=3 and dv[t].iloc[i]>=2e6): continue
            last=i; r=c.iloc[i+n]/c.iloc[i]-1
            b=(spy.iloc[i+n]/spy.iloc[i]-1) if vs=='spy' else (bkc.iloc[i+n]/bkc.iloc[i]-1)
            rows.append((c.index[i].year,r-b-cost))
    x=pd.DataFrame(rows,columns=['yr','e'])
    out=[]
    for era,m in (('08-18',x.yr<=2018),('19-26',x.yr>=2019)):
        y=x[m].e; out.append(f'{era} n={len(y):4d} {y.mean()*100:+.2f}% (t {y.mean()/y.std()*np.sqrt(len(y)) if len(y)>2 else 0:.1f})')
    print(f'{label:56s} '+' | '.join(out))
d3=lambda t:(C[t].diff()<0)&(C[t].diff().shift(1)<0)&(C[t].diff().shift(2)<0)
test(MIN,d3,'3 down days, miners, 5d vs S&P')
test(NUC,d3,'3 down days, our 10, 5d vs S&P')
test(NUC,d3,'3 down days, our 10, 5d vs our basket',vs='bk')
h52=lambda t:(C[t]>=hi[t].shift(1))
test(MIN,h52,'new 52-week high, miners, 5d vs S&P')
test(NUC,h52,'new 52-week high, our 10, 5d vs our basket',vs='bk')
l52=lambda t:(C[t]<=lo[t].shift(1))
test(MIN,l52,'new 52-week low, miners, 5d vs S&P')
test(NUC,l52,'new 52-week low, our 10, 5d vs S&P')
test(NUC,l52,'new 52-week low, our 10, 20d vs S&P',n=20,gap=20)
