import yfinance as yf, pandas as pd, pickle, warnings; warnings.filterwarnings('ignore')
d=pd.read_pickle('/tmp/sz/daily_max.pkl')['Close']
tk=[t for t in d.columns if t!='SPY']+['URA','URNM','SRUUF','U-UN.TO','URNJ','NLR']
out={}
for t in tk:
    try:
        s=yf.Ticker(t).get_shares_full(start='2010-01-01')
        if s is not None and len(s)>10:
            s=s[~s.index.duplicated(keep='last')]; s.index=s.index.tz_localize(None) if s.index.tz is not None else s.index; out[t]=s.sort_index()
    except Exception as e: pass
pickle.dump(out,open('shares.pkl','wb'))
print(len(out),'of',len(tk)); 
for t in ['URA','URNM','SRUUF','CCJ','DNN','UEC']:
    if t in out: print(t,out[t].index[0].date(),out[t].index[-1].date(),len(out[t]),int(out[t].iloc[0]),int(out[t].iloc[-1]))
