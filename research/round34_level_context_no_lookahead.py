import pandas as pd, numpy as np, yfinance as yf, warnings; warnings.filterwarnings('ignore')
tr=pd.read_pickle('/tmp/r34/tr.pkl')
spyH=yf.download('SPY',period='730d',interval='1h',auto_adjust=True,progress=False)['Close'].squeeze()
spyH.index=spyH.index.tz_convert('America/New_York').tz_localize(None)
spyD=yf.download('SPY',start='2023-06-01',auto_adjust=True,progress=False)['Close'].squeeze()
v=[]
for _,x in tr.iterrows():
    d=x.date; pc=spyD[spyD.index<d]
    h=spyH[spyH.index<x.ts]            # strictly bars that STARTED before the fill bar = known at the fill
    if len(pc)==0 or len(h)==0 or h.index[-1].date()!=d.date(): v.append(np.nan); continue
    v.append(h.iloc[-1]/pc.iloc[-1]-1)
tr['spy_known']=v
print('fills with an S&P reading known before the fill:',tr.spy_known.notna().sum(),'of',len(tr),'(9:30 fills have none)')
half=tr.entry.iloc[len(tr)//2]; nuc=tr.group=='uranium/nuclear'
def test(name,mask,base=None):
    base=base if base is not None else tr.spy_known.notna()
    out=[]
    for lab,part in (('older',tr.entry<half),('newer',tr.entry>=half),('nuclear',nuc),('others',~nuc)):
        a=tr[part&mask].R; r=tr[part&~mask&base].R
        se=np.sqrt(a.var()/max(len(a),1)+r.var()/len(r)); out.append(f"{lab}: n {len(a)} R {a.mean():+.3f} vs {r.mean():+.3f} (t {(a.mean()-r.mean())/se:+.1f})")
    print(f"{name:34s}",' | '.join(out))
test('S&P down 1%+ before the fill', tr.spy_known<-0.01)
test('S&P down 0.5-1% before the fill', (tr.spy_known<-0.005)&(tr.spy_known>=-0.01))
test('S&P up 0.5%+ before the fill', tr.spy_known>0.005)
b2=tr.dist200.notna()
test('stock below its 200-day', tr.dist200<0, b2)
test('far above 6-month weekly low (40%+)', tr.wsup>0.40, b2)
test('within 5% of 6-month weekly low', tr.wsup<0.05, b2)
tr.to_pickle('/tmp/r34/tr2.pkl')
