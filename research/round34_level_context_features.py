import json, pandas as pd, numpy as np, yfinance as yf, warnings; warnings.filterwarnings('ignore')
S=json.load(open('/tmp/st_live.json')); tr=pd.DataFrame(S['shadow_desk']['trades']).sort_values('entry')
tr['date']=pd.to_datetime(tr.entry.str[:10]); tr['ts']=pd.to_datetime(tr.entry)
tk=sorted(tr.tk.unique())
raw=yf.download(tk+['SPY'],start='2022-06-01',auto_adjust=True,progress=False)
C,L=raw['Close'],raw['Low']
spyH=yf.download('SPY',period='730d',interval='1h',auto_adjust=True,progress=False)['Close']
spyH=spyH.squeeze(); spyH.index=spyH.index.tz_convert('America/New_York').tz_localize(None)
f=[]
for _,x in tr.iterrows():
    t=x.tk; d=x.date
    c=C[t].dropna(); l=L[t].dropna()
    prev=c[c.index<d]; pl=l[l.index<d]
    if len(prev)<210: f.append((np.nan,np.nan,np.nan)); continue
    ma200=prev.tail(200).mean(); dist200=prev.iloc[-1]/ma200-1
    # weekly support: lowest weekly low of the prior 26 weeks (excluding the current week); is the fill within 3% above it?
    wk=pl.resample('W-FRI').min().iloc[:-1].tail(26)
    entry_px=prev.iloc[-1]*(1+x.ret_pct/100*0)  # approximate the fill by yesterday's close (the level sits near it)
    wsup=(entry_px/wk.min()-1) if len(wk) else np.nan
    # S&P move from yesterday's close to the fill hour
    sc=C['SPY'].dropna(); sp_prev=sc[sc.index<d].iloc[-1]
    h=spyH[spyH.index<=x.ts]; spm=(h.iloc[-1]/sp_prev-1) if len(h) and h.index[-1].date()==d.date() else np.nan
    f.append((dist200,wsup,spm))
tr[['dist200','wsup','spy_day']]=pd.DataFrame(f,index=tr.index)
tr.to_pickle('/tmp/r34/tr.pkl')
half=tr.entry.iloc[len(tr)//2]
def test(name,mask):
    out=[]
    for lab,part in (('older',tr.entry<half),('newer',tr.entry>=half)):
        a=tr[part&mask].R; r=tr[part&~mask&tr.dist200.notna()].R
        se=np.sqrt(a.var()/max(len(a),1)+r.var()/len(r)); out.append(f"{lab}: n {len(a)} R {a.mean():+.3f} vs {r.mean():+.3f} (t {(a.mean()-r.mean())/se:+.1f})")
    print(f"{name:40s}",' | '.join(out))
test('above 200-day by 30%+', tr.dist200>0.30)
test('below 200-day', tr.dist200<0)
test('below 200-day by 20%+', tr.dist200<-0.20)
test('fill near a 6-month weekly low (<5%)', tr.wsup<0.05)
test('far above weekly support (>40%)', tr.wsup>0.40)
test('S&P down 1%+ at fill time', tr.spy_day<-0.01)
test('S&P up 0.5%+ at fill time', tr.spy_day>0.005)
