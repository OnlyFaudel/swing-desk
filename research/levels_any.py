"""Level front-run on HOURLY swing points (more frequent opportunities) vs the daily version.
Entry: resting limit just above the nearest confirmed hourly swing-low support; stop under the zone;
target: nearest hourly swing-high resistance; require reward >= rr x risk. Max hold N hours. Cost 0.1% RT."""
import yfinance as yf, pandas as pd, numpy as np
import sys
T=sys.argv[1].split(",")
H=yf.download(T,period="730d",interval="1h",auto_adjust=True,progress=False)
def g(t):
    x=H.xs(t,axis=1,level=1).dropna(); x.index=x.index.tz_convert("America/New_York"); return x
def run(k=5,front=0.004,pad=0.012,rr=2.0,maxh=21,look=70,trend=False):
    out=[]
    for t in T:
        h=g(t); lo=h.Low==h.Low.rolling(2*k+1,center=True).min(); hi=h.High==h.High.rolling(2*k+1,center=True).max()
        sma=h.Close.rolling(7*50).mean()
        i=look+k; n=len(h)
        while i<n-1:
            prev=h.Close.iloc[i-1]
            sup=[h.Low.iloc[j] for j in range(i-look,i-k) if lo.iloc[j] and h.Low.iloc[j]<prev*0.995]
            res=[h.High.iloc[j] for j in range(i-look*2,i-k) if hi.iloc[j] and h.High.iloc[j]>prev*1.01]
            if not sup or not res or (trend and not prev>sma.iloc[i-1]): i+=1; continue
            Z=max(sup); R=min(res); e=Z*(1+front); s=Z*(1-pad)
            if R-e<rr*(e-s) or e>=prev: i+=1; continue
            # order rests for the next 7 hourly bars (about one session)
            filled=None
            for j in range(i,min(i+7,n)):
                if h.Low.iloc[j]<=e: filled=j; break
            if filled is None: i+=1; continue
            ep=min(e,h.Open.iloc[filled]); res_=None
            for j in range(filled,min(filled+maxh,n)):
                r=h.iloc[j]
                if r.Low<=s: res_=(min(s,r.Open)/ep-1,j); break
                if r.High>=R and j>filled: res_=(max(R,r.Open)/ep-1,j); break
            if res_ is None: j=min(filled+maxh,n-1); res_=(h.Close.iloc[j]/ep-1,j)
            out.append((t,res_[0]-0.001)); i=res_[1]+1
    r=pd.Series([x[1] for x in out]); by={t:round(np.mean([x[1] for x in out if x[0]==t])*100,2) for t in T}
    wk=len(r)/(730/7*5/7)
    return f"trades {len(r)} (~{len(r)/104:.1f}/week) win {100*(r>0).mean():.0f}% avg {100*r.mean():+.2f}% W {100*r[r>0].mean():+.2f}% L {100*r[r<=0].mean():+.2f}% t={r.mean()/r.std()*np.sqrt(len(r)):.2f} | by stock {by}"
for kw in [dict(rr=1.5),dict()]:
    print(f"{str(kw or 'default (k=5,rr=2,hold<=3 days)'):34s}", run(**kw))
