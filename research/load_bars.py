import yfinance as yf, pandas as pd, warnings, pickle
warnings.filterwarnings("ignore")
T=["CCJ","MU","PLTR","TSM","ETN","SPY"]; out={"h":{}, "d":{}}
for t in T:
    h=yf.download(t,period="729d",interval="1h",auto_adjust=True,progress=False); h.columns=h.columns.get_level_values(0)
    h=h.dropna(); h.index=h.index.tz_convert("America/New_York"); out["h"][t]=h
    d=yf.download(t,start="2023-01-01",auto_adjust=True,progress=False); d.columns=d.columns.get_level_values(0); out["d"][t]=d.dropna()
pickle.dump(out,open("bars.pkl","wb")); print({t:len(v) for t,v in out["h"].items()})
