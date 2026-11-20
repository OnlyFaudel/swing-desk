"""Find CCJ's best partners for the level strategy, with a robustness guard:
a ticker must be positive in BOTH halves (hourly: year 1 vs year 2; daily: 2015-20 vs 2021-26)."""
import yfinance as yf, pandas as pd, numpy as np, json, sys, warnings
warnings.filterwarnings("ignore")
U={"uranium/nuclear":["CCJ","UEC","NXE","LEU","CEG","VST","TLN","BWXT","OKLO","SMR","GEV"],
   "AI power infra":["VRT","ETN","PWR","NRG"],
   "AI chips":["NVDA","MU","AVGO","AMD","TSM"], "other":["PLTR"]}
ALL=[t for v in U.values() for t in v]
def hourly_trades(h,k=5,front=0.004,pad=0.012,rr=1.5,maxh=21,look=70):
    lo=h.Low==h.Low.rolling(2*k+1,center=True).min(); hi=h.High==h.High.rolling(2*k+1,center=True).max()
    out=[]; i=look*2+k; n=len(h)
    while i<n-1:
        prev=h.Close.iloc[i-1]
        sup=[h.Low.iloc[j] for j in range(i-look,i-k) if lo.iloc[j] and h.Low.iloc[j]<prev*0.995]
        res=[h.High.iloc[j] for j in range(i-look*2,i-k) if hi.iloc[j] and h.High.iloc[j]>prev*1.01]
        if not sup or not res: i+=1; continue
        Z=max(sup); R=min(res); e=Z*(1+front); s=Z*(1-pad)
        if R-e<rr*(e-s) or e>=prev: i+=1; continue
        f=next((j for j in range(i,min(i+7,n)) if h.Low.iloc[j]<=e),None)
        if f is None: i+=1; continue
        ep=min(e,h.Open.iloc[f]); res_=None
        for j in range(f,min(f+maxh,n)):
            r=h.iloc[j]
            if r.Low<=s: res_=(min(s,r.Open)/ep-1,j); break
            if r.High>=R and j>f: res_=(max(R,r.Open)/ep-1,j); break
        if res_ is None: j=min(f+maxh,n-1); res_=(h.Close.iloc[j]/ep-1,j)
        out.append((h.index[f],res_[0]-0.001)); i=res_[1]+1
    return out
def daily_trades(d,k=5,front=0.004,pad=0.012,rr=2.0,maxd=10):
    lo=d.Low==d.Low.rolling(2*k+1,center=True).min(); hi=d.High==d.High.rolling(2*k+1,center=True).max()
    out=[]; i=130; n=len(d)
    while i<n-1:
        prev=d.Close.iloc[i-1]
        sup=[d.Low.iloc[j] for j in range(i-60,i-k) if lo.iloc[j] and d.Low.iloc[j]<prev*0.995]
        res=[d.High.iloc[j] for j in range(i-120,i-k) if hi.iloc[j] and d.High.iloc[j]>prev*1.01]
        if not sup or not res: i+=1; continue
        Z=max(sup); R=min(res); e=Z*(1+front); s=Z*(1-pad)
        if R-e<rr*(e-s) or e>=prev or d.Low.iloc[i]>e: i+=1; continue
        ep=min(e,d.Open.iloc[i]); res_=None
        if d.Low.iloc[i]<=s: res_=(s/ep-1,i)   # conservative: same-day stop first
        else:
            for j in range(i+1,min(i+1+maxd,n)):
                r=d.iloc[j]
                if r.Low<=s: res_=(min(s,r.Open)/ep-1,j); break
                if r.High>=R: res_=(max(R,r.Open)/ep-1,j); break
        if res_ is None: j=min(i+maxd,n-1); res_=(d.Close.iloc[j]/ep-1,j)
        out.append((d.index[i],res_[0]-0.001)); i=res_[1]+1
    return out
rows=[]; rets={}
DD=yf.download(ALL,start="2014-06-01",auto_adjust=True,progress=False)
for t in ALL:
    try:
        h=yf.download(t,period="729d",interval="1h",auto_adjust=True,progress=False)
        h.columns=h.columns.get_level_values(0); h=h.dropna(); h.index=h.index.tz_convert("America/New_York")
        ht=hourly_trades(h)
    except Exception as e:
        ht=[]
    d=DD.xs(t,axis=1,level=1).dropna()
    dt_=daily_trades(d)
    hs=pd.Series([r for _,r in ht],index=[x for x,_ in ht],dtype=float)
    ds=pd.Series([r for _,r in dt_],index=[x for x,_ in dt_],dtype=float)
    mid=hs.index[0]+(hs.index[-1]-hs.index[0])/2 if len(hs) else None
    h1=hs[hs.index<mid].mean()*100 if len(hs) else np.nan; h2=hs[hs.index>=mid].mean()*100 if len(hs) else np.nan
    d1=ds[ds.index<"2021-01-01"].mean()*100; d2=ds[ds.index>="2021-01-01"].mean()*100
    rows.append(dict(t=t,group=[g for g,v in U.items() if t in v][0],h_n=len(hs),h_avg=round(hs.mean()*100,3) if len(hs) else np.nan,
                     h_y1=round(h1,3),h_y2=round(h2,3),d_n=len(ds),d_15_20=round(d1,2),d_21_26=round(d2,2),
                     dollar_vol_m=round(float((d.Close*d.Volume).iloc[-60:].mean())/1e6)))
    rets[t]=d.Close.pct_change()
df=pd.DataFrame(rows)
df["robust"]=(df.h_y1>0)&(df.h_y2>0)&((df.d_15_20>0)|df.d_15_20.isna())&(df.d_21_26>0)
pd.set_option("display.width",200)
print(df.sort_values(["robust","h_avg"],ascending=False).to_string(index=False))
R=pd.DataFrame(rets).loc["2024-11-01":]
print("\n1-yr+ daily correlation with CCJ:", R.corr()["CCJ"].round(2).sort_values().to_dict())
df.to_csv("trio_search.csv",index=False); R.to_pickle("trio_rets.pkl")
