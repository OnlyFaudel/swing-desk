import pandas as pd, numpy as np, yfinance as yf, warnings; warnings.filterwarnings('ignore')
d=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']; ours=['CCJ','UEC','DNN','UUUU','NXE','LEU','BWXT','CEG','VST','TLN']
rel=[t for t in d.columns if t not in ours+['SPY']]
M=d.resample('ME').last().pct_change()
print('1) month of quarter, basket minus S&P per month')
for lab,names in (('our 10',ours),('related',rel)):
    ex=M[names].mean(axis=1)-M['SPY']; pos=((ex.index.month-1)%3)+1
    for era,(a,b) in {'00-07':('2000','2008'),'08-18':('2008','2019'),'19-26':('2019','2027')}.items():
        m=(ex.index>=a)&(ex.index<b)
        print(f"   {lab:8s} {era}: "+' | '.join(f"month {p}: {ex[m&(pos==p)].mean()*100:+.2f}%" for p in (1,2,3)))
print('2) VWAP on a 5%+ down day (minute data, 11 stocks): close vs VWAP -> next 5 days (raw, cost 0.2%)')
x=pd.read_pickle('/tmp/r15/intraday.pkl').sort_values(['t','date']); x['date']=pd.to_datetime(x.date); g=x.groupby('t')
x['r']=x.close/g.close.shift(1)-1; x['f5']=g.close.shift(-5)/x.close-1-0.002
spy=d['SPY']; x['s5']=[spy.asof(dd+pd.Timedelta(days=7))/spy.asof(dd)-1 for dd in x.date]
x['f5x']=x.f5-x.s5
dn=x[x.r<=-0.05]
for era,(a,b) in {'16-20':('2016','2021'),'21-26':('2021','2027')}.items():
    y=dn[(dn.date>=a)&(dn.date<b)]
    above=y[y.close>y.vwap*1.005]; below=y[y.close<y.vwap*0.99]
    print(f"   {era}: closed above VWAP {above.f5x.mean()*100:+.2f}% n{len(above)} | closed 1%+ below VWAP {below.f5x.mean()*100:+.2f}% n{len(below)} | all {y.f5x.mean()*100:+.2f}%")
print('3) ex-dividend days in power names')
rows=[]
for t in ['CEG','VST','NRG','PEG','EXC','ETR','D','DUK','SO','AEP']:
    try:
        tk=yf.Ticker(t); dv=tk.dividends; h=tk.history(start='2005-01-01',auto_adjust=False)['Close']
    except Exception: continue
    if dv is None or len(dv)==0: continue
    dv.index=dv.index.tz_localize(None); h.index=h.index.tz_localize(None)
    sp=spy
    for dd,amt in dv.items():
        if dd not in h.index: continue
        i=h.index.get_loc(dd)
        if i<6 or i+5>=len(h): continue
        pre=h.iloc[i-1]/h.iloc[i-6]-1-(sp.asof(h.index[i-1])/sp.asof(h.index[i-6])-1)   # run-up into ex-date (prices not dividend-adjusted)
        post=(h.iloc[i+5]+0)/h.iloc[i-1]-1+amt/h.iloc[i-1]-(sp.asof(h.index[i+5])/sp.asof(h.index[i-1])-1)  # hold through ex incl dividend
        rows.append((dd,t,pre,post,amt/h.iloc[i-1]))
r=pd.DataFrame(rows,columns=['d','t','pre','post','yld'])
for era,(a,b) in {'05-12':('2005','2013'),'13-19':('2013','2020'),'20-26':('2020','2027')}.items():
    y=r[(r.d>=a)&(r.d<b)]
    print(f"   {era}: 5 days into ex-date vs S&P {y.pre.mean()*100:+.2f}% (t {y.pre.mean()/y.pre.std()*np.sqrt(len(y)):+.1f}) | hold through ex 5d incl. dividend {y.post.mean()*100:+.2f}% | n{len(y)} avg dividend {y.yld.mean()*100:.2f}%")
