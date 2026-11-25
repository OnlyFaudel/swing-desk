"""Intraday order-flow features from Alpaca minute bars, one row per stock per day (owner's order-flow idea, 2026-11-24).

True order flow (every trade tagged buyer- or seller-initiated) needs tick data far too big for this repo, so this uses the
standard bar-level stand-in: volume on minutes that closed up counts as buying pressure, volume on minutes that closed down
as selling pressure. 'Pressure' = (buy volume - sell volume) / total volume, from -1 (all selling) to +1 (all buying).

Run on the server (it has the Alpaca keys):  python intraday.py backfill   (once, ~1 hour, resumable)
                                            python intraday.py daily      (after each close)
Output: data/intraday/YYYY-MM.csv (one file per month so daily commits stay small).
"""
import os, sys, json, time, datetime as dt
import pandas as pd

OUT = "data/intraday"
PROG = os.path.join(OUT, "_progress_v3.json")  # v3 adds pre-market / after-hours columns (v1 had a 0-row bug)
COLS = ["t", "date", "prev_close", "open", "px935", "px945", "px1000", "px1530", "close", "low", "high", "vol", "vol15",
        "press15", "press30", "press_last30", "press_day", "vwap", "low_min", "high_min", "feed",
        "pre_px", "pre_vol", "ah_px", "ah_vol", "ah_high", "ah_low"]  # pre-market 4:00-9:30 (same day), after hours 16:00-20:00


def _client():
    from alpaca.data.historical import StockHistoricalDataClient
    return StockHistoricalDataClient(os.environ["ALPACA_KEY"], os.environ["ALPACA_SECRET"])


def _bars(cl, t, start, end, feed):
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import Adjustment, DataFeed
    req = StockBarsRequest(symbol_or_symbols=t, timeframe=TimeFrame.Minute, start=start, end=end,
                           adjustment=Adjustment.ALL, feed=DataFeed.SIP if feed == "sip" else DataFeed.IEX)
    df = cl.get_stock_bars(req).df
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.reset_index()
    df["ts"] = pd.to_datetime(df["timestamp"]).dt.tz_convert("America/New_York")
    return df[["ts", "open", "high", "low", "close", "volume"]]


def _press(g):
    v = g["volume"].sum()
    if not v:
        return None
    sign = (g["close"] > g["open"]).astype(int) - (g["close"] < g["open"]).astype(int)
    return round(float((g["volume"] * sign).sum() / v), 4)


def features(df, t, feed):
    out = []
    tt = df.ts.dt.time
    ext = {}
    for day, g in df[(tt < dt.time(9, 30)) | (tt >= dt.time(16, 0))].groupby(df.ts.dt.date):
        pre, ah = g[g.ts.dt.time < dt.time(9, 30)], g[g.ts.dt.time >= dt.time(16, 0)]
        ext[day] = {"pre_px": float(pre.close.iloc[-1]) if len(pre) else None, "pre_vol": int(pre.volume.sum()),
                    "ah_px": float(ah.close.iloc[-1]) if len(ah) else None, "ah_vol": int(ah.volume.sum()),
                    "ah_high": float(ah.high.max()) if len(ah) else None, "ah_low": float(ah.low.min()) if len(ah) else None}
    df = df[(tt >= dt.time(9, 30)) & (tt < dt.time(16, 0))]
    for day, g in df.groupby(df.ts.dt.date):
        g = g.sort_values("ts")
        if len(g) < 60:
            continue
        tm = g.ts.dt.time
        at = lambda h, m: (float(g[tm <= dt.time(h, m)].close.iloc[-1]) if (tm <= dt.time(h, m)).any() else None)
        f15, f30, l30 = g[tm < dt.time(9, 45)], g[tm < dt.time(10, 0)], g[tm >= dt.time(15, 30)]
        mins = ((g.ts - g.ts.iloc[0]).dt.total_seconds() // 60).astype(int)
        out.append({"t": t, "date": str(day), "prev_close": None, "open": float(g.open.iloc[0]), "px935": at(9, 34), "px945": at(9, 44),
                    "px1000": at(9, 59), "px1530": at(15, 29), "close": float(g.close.iloc[-1]), "low": float(g.low.min()),
                    "high": float(g.high.max()), "vol": int(g.volume.sum()), "vol15": int(f15.volume.sum()),
                    "press15": _press(f15), "press30": _press(f30), "press_last30": _press(l30), "press_day": _press(g),
                    "vwap": round(float((g.close * g.volume).sum() / max(1, g.volume.sum())), 4),
                    "low_min": int(mins.iloc[g.low.values.argmin()]), "high_min": int(mins.iloc[g.high.values.argmax()]), "feed": feed,
                    **ext.get(day, {"pre_px": None, "pre_vol": 0, "ah_px": None, "ah_vol": 0, "ah_high": None, "ah_low": None})})
    return out


def _write(rows):
    if not rows:
        return
    os.makedirs(OUT, exist_ok=True)
    new = pd.DataFrame(rows)
    for month, part in new.groupby(new.date.str[:7]):
        p = os.path.join(OUT, f"{month}.csv")
        old = pd.read_csv(p) if os.path.exists(p) else pd.DataFrame(columns=COLS)
        allr = pd.concat([old, part[COLS]]).drop_duplicates(["t", "date"], keep="last").sort_values(["date", "t"])
        allr.to_csv(p, index=False)


def universe():
    cfg = json.load(open("config.json"))
    st = json.load(open("state.json")) if os.path.exists("state.json") else {}
    lineup = st.get("active") or ["CCJ", "NXE", "UEC", "DNN", "UUUU", "LEU", "BWXT", "CEG", "VST", "TLN"]
    extra = ["OKLO", "SMR", "NNE", "URG", "SPY"]
    return list(dict.fromkeys(lineup + extra + (cfg.get("panic_rebound", {}).get("related_universe") or [])))


def pull(tickers, start, end, resume=True):
    cl = _client()
    prog = json.load(open(PROG)) if (resume and os.path.exists(PROG)) else {}
    for t in tickers:
        if resume and isinstance(prog.get(t), dict) and prog[t].get("done"):
            continue
        rows, feed, fails, last_err = [], "sip", 0, ""
        y = start
        while y < end:
            y2 = min(end, y + dt.timedelta(days=90))
            for attempt in range(3):
                try:
                    try:
                        df = _bars(cl, t, y, y2, feed)
                    except Exception as e:
                        if feed == "sip" and ("subscription" in str(e).lower() or "403" in str(e) or "forbidden" in str(e).lower()):
                            feed = "iex"
                            df = _bars(cl, t, y, y2, feed)
                        else:
                            raise
                    rows += features(df, t, feed)
                    break
                except Exception as e:
                    print("intraday", t, y, repr(e)[:200], flush=True)
                    last_err = repr(e)[:200]
                    if attempt == 2:
                        fails += 1
                    time.sleep(5 * (attempt + 1))
            y = y2
            time.sleep(0.35)  # stay well under the API rate limit
        _write(rows)
        if resume:
            # only 'done' if most chunks worked; otherwise the next launch retries this stock
            prog[t] = {"done": bool(rows) and fails <= 2, "days": len(rows), "failed_chunks": fails, "feed": feed, "err": last_err}
            os.makedirs(OUT, exist_ok=True)
            json.dump(prog, open(PROG, "w"))
        print(f"intraday {t}: {len(rows)} days ({feed}), {fails} failed chunks {last_err}", flush=True)
    if resume:
        prog["_complete"] = all((prog.get(t) or {}).get("done") for t in tickers)
        json.dump(prog, open(PROG, "w"))


def _locked():
    lk = os.path.join(OUT, "_lock")
    if os.path.exists(lk):
        try:
            os.kill(int(open(lk).read().strip()), 0)
            return True  # another pull is still running
        except Exception:
            pass
    os.makedirs(OUT, exist_ok=True)
    open(lk, "w").write(str(os.getpid()))
    return False


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if _locked():
        sys.exit(0)
    now = dt.datetime.now(dt.timezone.utc)
    end = (now - dt.timedelta(minutes=20)).replace(second=0, microsecond=0)  # SIP history needs to be 15+ min old
    if mode == "backfill":
        pull(universe(), dt.datetime(2016, 1, 1, tzinfo=dt.timezone.utc), end, resume=True)
    else:
        pull(universe(), end - dt.timedelta(days=4), end, resume=False)
