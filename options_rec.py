"""Options Recorder: every trading day before the close, save the option chains for the trio.
Historical option prices cost money to buy; recording our own from today builds the dataset for later option ideas
(e.g. buying puts/calls when the bot has a measured record of calling moves). One gzip CSV per day in data/options/."""
import os, datetime as dt
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data", "options")
COLS = ["contractSymbol", "strike", "lastPrice", "bid", "ask", "volume", "openInterest", "impliedVolatility", "inTheMoney"]


def record(tickers, max_days=70, today=None):
    import yfinance as yf
    today = today or dt.date.today()
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{today}.csv.gz")
    frames, stats = [], {}
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    for t in tickers:
        tk = yf.Ticker(t)
        try:
            spot = float(tk.history(period="1d", interval="5m").Close.iloc[-1])
        except Exception:
            spot = None
        n = 0
        for e in tk.options:
            if (dt.date.fromisoformat(e) - today).days > max_days:
                break
            try:
                ch = tk.option_chain(e)
            except Exception:
                continue
            for kind, df in (("call", ch.calls), ("put", ch.puts)):
                d = df[[c for c in COLS if c in df.columns]].copy()
                d.insert(0, "type", kind); d.insert(0, "expiry", e); d.insert(0, "underlying", t)
                d["spot"], d["recorded"] = spot, stamp
                frames.append(d); n += len(d)
        stats[t] = n
    if frames:
        pd.concat(frames).to_csv(path, index=False, compression="gzip")
    return {"path": os.path.relpath(path, ROOT), "contracts": stats, "files": len(os.listdir(OUT))}


def put_call_snapshot(path):
    """Quick read of one day's file: put/call volume and open-interest ratios per stock."""
    d = pd.read_csv(path)
    out = {}
    for t, g in d.groupby("underlying"):
        v = g.groupby("type").volume.sum(); oi = g.groupby("type").openInterest.sum()
        out[t] = {"pc_volume": round(v.get("put", 0) / max(v.get("call", 0), 1), 2),
                  "pc_open_interest": round(oi.get("put", 0) / max(oi.get("call", 0), 1), 2)}
    return out
