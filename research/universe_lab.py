import yfinance as yf, pandas as pd, numpy as np, pickle, warnings
from level_engine import prep, simulate, stats
warnings.filterwarnings("ignore")
U=["CCJ","UEC","NXE","LEU","CEG","VST","TLN","BWXT","OKLO","SMR","VRT","ETN","PWR","NRG","NVDA","MU","AVGO","AMD","TSM","PLTR",
   "SMH","URA","XLU","QQQ","SPY"]
B=pickle.load(open("bars.pkl","rb")); H=dict(B["h"])
for t in U:
    if t in H: continue
    try:
        h=yf.download(t,period="729d",interval="1h",auto_adjust=True,progress=False); h.columns=h.columns.get_level_values(0)
        h=h.dropna(); h.index=h.index.tz_convert("America/New_York"); H[t]=h
    except Exception as e: print("skip",t,e)
pickle.dump({"h":H,"d":B["d"]},open("bars_universe.pkl","wb"))
rows=[]; ALLTR={}
for t in U:
    if t not in H or len(H[t])<1500: continue
    h=prep(H[t]); mid=h.index[len(h)//2]
    for name,p in {"old (1d)":{"valid":7},"patient (5d)":{"valid":35}}.items():
        xs=simulate(h,p); a=stats([x for x in xs if x[0]<mid]); b=stats([x for x in xs if x[0]>=mid])
        rows.append(dict(t=t,rule=name,train=a["avg"],test=b["avg"],n_test=b["n"],t_test=b["t"]))
        if name.startswith("patient"): ALLTR[t]=xs
df=pd.DataFrame(rows).pivot(index="t",columns="rule",values=["train","test"])
df.columns=[f"{a} {b}" for a,b in df.columns]; df=df.sort_values("test patient (5d)",ascending=False)
print(df.round(3).to_string())
p=df["test patient (5d)"]; o=df["test old (1d)"]
print(f"\npatient rule positive in year 2 on {int((p>0).sum())}/{len(p)} tickers (old rule: {int((o>0).sum())}/{len(o)}); median year-2 avg {p.median():+.3f}% vs {o.median():+.3f}%")
pickle.dump(ALLTR,open("patient_trades.pkl","wb"))
