import yfinance as yf, pandas as pd, numpy as np
N=["CCJ","CEG","VST","LEU","BWXT","GEV","OKLO"]; OLD=["CCJ","MU","PLTR"]
D=yf.download(N+["MU","PLTR","SPY"],start="2023-11-01",auto_adjust=True,progress=False)["Close"]
r=D.pct_change().dropna(how="all")
print("Daily correlation, last 2 years:")
print(r[N].corr().round(2).to_string())
avg=lambda cols:(r[cols].corr().values[np.triu_indices(len(cols),1)]).mean()
print(f"\navg pairwise correlation: current trio {avg(OLD):.2f} | CCJ+CEG+BWXT {avg(['CCJ','CEG','BWXT']):.2f} | CCJ+LEU+BWXT {avg(['CCJ','LEU','BWXT']):.2f} | CCJ+VST+GEV {avg(['CCJ','VST','GEV']):.2f}")
print("\nLead-lag: does yesterday's move in A predict today's move in B? (correlation, |x|>0.08 is notable)")
for a in N:
    row={b:round(r[a].shift(1).corr(r[b]),2) for b in N if b!=a}
    print(f"  {a:5s} yesterday ->", row)
# worst common days
basket=r[["CCJ","CEG","BWXT"]].mean(axis=1); old=r[OLD].mean(axis=1)
print(f"\nWorst single day, equal-weight basket: nuclear chain {basket.min()*100:.1f}% | current trio {old.min()*100:.1f}%")
print(f"Basket volatility (annual): nuclear chain {basket.std()*np.sqrt(252)*100:.0f}% | current trio {old.std()*np.sqrt(252)*100:.0f}%")
last=D.iloc[-2] if D.iloc[-1].isna().any() else D.iloc[-1]
print("\nPrice now (1 option contract = 100 shares):", {t:round(float(last[t]),2) for t in N})
