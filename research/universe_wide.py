"""Patient Levels (live params, fixed engine) on a wide universe, 730 days of hourly bars.
Pick on the first half, judge on the second half, so 'best stock' is not just luck."""
import sys, time, pickle, numpy as np, pandas as pd, yfinance as yf
sys.path.insert(0, ".."); import patient
U = {"uranium/nuclear": ["CCJ","NXE","UEC","DNN","UUUU","LEU","BWXT","SMR","OKLO","CEG","VST","TLN","URNM"],
     "scarce materials": ["MP","ALB","FCX","SCCO","NEM","AEM","WPM","SQM","TECK"],
     "AI chips": ["NVDA","AMD","AVGO","MU","TSM","ASML","ARM","MRVL","SMCI","SMH"],
     "AI power": ["ETN","VRT","GEV","PWR","NRG"],
     "high beta": ["PLTR","TSLA","COIN","MSTR","HOOD","SOFI","RKLB","IONQ","APP","SHOP","NOK"],
     "megacap": ["META","AMZN","MSFT","GOOGL","NFLX"]}
tick = [t for v in U.values() for t in v]
bars = {}
for i in range(0, len(tick), 10):
    ch = tick[i:i+10]
    for a in range(3):
        try:
            d = yf.download(ch, period="730d", interval="1h", auto_adjust=True, progress=False, group_by="ticker", threads=True); break
        except Exception as e:
            print("retry", e); time.sleep(10)
    for t in ch:
        try:
            h = d[t][["Open","High","Low","Close"]].dropna()
            h["Volume"] = 1.0; h.index = h.index.tz_convert("America/New_York")
            if len(h) > 2000: bars[t] = h
        except Exception as e: print("miss", t, e)
    time.sleep(3)
pickle.dump(bars, open("bars_wide.pkl", "wb"))
mid = pd.Timestamp("2025-11-20", tz="America/New_York")
rows = []
for g, ts in U.items():
    for t in ts:
        if t not in bars: continue
        tr = patient.simulate(patient.prep(bars[t]), patient.LIVE)
        a = np.array([x[2] for x in tr if x[0] < mid]); b = np.array([x[2] for x in tr if x[0] >= mid])
        tt = lambda r: r.mean()/r.std()*np.sqrt(len(r)) if len(r) > 5 else np.nan
        w = bars[t].Close.resample("W-FRI").last().pct_change().std()*100
        rows.append(dict(group=g, tk=t, n1=len(a), avg1=a.mean()*100, t1=tt(a), n2=len(b), avg2=b.mean()*100, t2=tt(b), wk_vol=w))
df = pd.DataFrame(rows)
df.to_csv("universe_wide.csv", index=False)
pd.set_option("display.width", 200)
print(df.sort_values("t1", ascending=False).round(2).to_string(index=False))
from scipy.stats import spearmanr
print("rank persistence half1 t vs half2 avg:", spearmanr(df.t1, df.avg2, nan_policy="omit"))
top = df.nlargest(5, "t1"); print("top5 by half1 -> half2 avg %", top.avg2.mean().round(3), "| all -> half2 avg %", df.avg2.mean().round(3))
print("trio half2 avg %", df[df.tk.isin(["CCJ","TSM","ETN"])].avg2.mean().round(3))
print("by group half2:", df.groupby("group").avg2.mean().round(3).to_dict())
print("vol vs half2 avg corr", np.corrcoef(df.wk_vol, df.avg2)[0,1].round(2))
