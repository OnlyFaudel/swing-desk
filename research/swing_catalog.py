"""Every big day and every up-swing for each lineup stock since 2007 (or its listing), with what happened next.
Writes research/big_moves.csv and research/swings_up.csv (read by the stock files). Run: python research/swing_catalog.py"""
import os, sys
import numpy as np, pandas as pd, yfinance as yf

T = ["CCJ", "NXE", "UEC", "DNN", "UUUU", "LEU", "BWXT", "CEG", "VST", "TLN"]
OUT = os.path.dirname(os.path.abspath(__file__))


def main(start="2006-01-01"):
    px = yf.download(T + ["SPY", "URA"], start=start, auto_adjust=True, progress=False)
    C, O, V = px["Close"], px["Open"], px["Volume"]
    R = C.pct_change()
    big, sw = [], []
    for t in T:
        c = C[t].dropna(); r = R[t]; others = [x for x in T if x != t]
        peer = R[others].median(axis=1); sig = r.rolling(60).std().shift(1)
        vr = V[t] / V[t].rolling(20).mean().shift(1); gap = O[t] / C[t].shift(1) - 1
        bk = (1 + R[others].mean(axis=1).fillna(0)).cumprod()
        idx = c.index
        for i, d in enumerate(idx):
            if i < 60 or pd.isna(r.get(d)) or pd.isna(sig.get(d)):
                continue
            z = r[d] / sig[d]
            if abs(z) >= 2.5 or abs(r[d]) >= 0.08:
                spy, p = R.SPY.get(d, np.nan), peer.get(d, np.nan)
                cat = ("market" if abs(spy) >= 0.015 and np.sign(spy) == np.sign(r[d]) == np.sign(p) else
                       "sector" if np.sign(p) == np.sign(r[d]) and abs(p) >= 0.5 * abs(r[d]) else "company")
                row = dict(ticker=t, date=d.date(), ret=round(r[d] * 100, 2), z=round(z, 2), gap=round(gap[d] * 100, 2), peer=round(p * 100, 2),
                           spy=round(spy * 100, 2), vol_ratio=round(vr[d], 2), cat=cat)
                for n in (1, 5, 10, 20):
                    if i + n < len(idx):
                        d2 = idx[i + n]
                        row[f"f{n}"] = round((c[d2] / c[d] - 1) * 100, 2); row[f"a{n}"] = round(((c[d2] / c[d]) / (bk[d2] / bk[d]) - 1) * 100, 2)
                big.append(row)
        hi20, ma50, last = c.rolling(20).max(), c.rolling(50).mean(), -10
        for i in range(60, len(idx) - 4):
            fut = c.iloc[i + 1:i + 5]; up = fut.max() / c.iloc[i] - 1
            thr = max(0.08, 2.0 * sig.iloc[i] * np.sqrt(3)) if not pd.isna(sig.iloc[i]) else 0.08
            if up < thr or c.iloc[i] > c.iloc[max(0, i - 3):i + 1].min() or i - last < 4:
                continue
            last = i; k = int(np.argmax(fut.values)) + 1; d = idx[i]
            sw.append(dict(ticker=t, low_date=d.date(), low=round(c.iloc[i], 2), peak_date=fut.index[k - 1].date(), days=k, swing=round(up * 100, 1),
                           day_ret=round(r.iloc[i] * 100, 2), spy=round(R.SPY.get(d, np.nan) * 100, 2), peer=round(peer.get(d, np.nan) * 100, 2),
                           ret10=round((c.iloc[i] / c.iloc[i - 10] - 1) * 100, 1), dd20=round((c.iloc[i] / hi20.iloc[i] - 1) * 100, 1),
                           vs50=round((c.iloc[i] / ma50.iloc[i] - 1) * 100, 1)))
    pd.DataFrame(big).to_csv(os.path.join(OUT, "big_moves.csv"), index=False)
    pd.DataFrame(sw).to_csv(os.path.join(OUT, "swings_up.csv"), index=False)
    return len(big), len(sw)


if __name__ == "__main__":
    print(main(*(sys.argv[1:2] or [])))
