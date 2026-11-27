"""Stocks in Play 5-minute opening-range breakout, replayed on real 1-minute bars (owner's question, 2026-11-26:
"how do day traders make their money?"). Rules follow Zarattini, Barbon & Aziz (2024), "A Profitable Day Trading
Strategy for the U.S. Equity Market":
  universe   every active US stock on Alpaca; on a given day it must open above $5, average 1M+ shares a day over the
             last 14 days, and have a 14-day ATR above $0.50
  in play    relative volume = volume in the first 5 minutes / average first-5-minute volume of the last 14 days (>= 1);
             the 20 highest each day are traded
  direction  first 5-minute candle up -> buy-stop at its high; down -> sell-stop at its low; flat -> no trade
  stop       10% of the 14-day ATR from the entry; otherwise out at the close
Each trade is replayed on 1-minute bars. If a bar touches both the entry and the stop, it is counted as stopped out
(conservative). Results go to data/orbsip/trades.csv; the analysis (costs, eras, long-only) is done separately.

Known bias: Alpaca only lists stocks that trade today, so names that were delisted since 2016 are missing.

Run on the server (it has the Alpaca keys):  python orbsip.py   (resumable; ~2 hours; only runs when the market is shut)
"""
import os, sys, json, time, sqlite3, datetime as dt
from collections import defaultdict, deque
import pandas as pd

OUT = "data/orbsip"
DB = "/home/desk/orbsip.sqlite" if os.path.isdir("/home/desk") else "/tmp/orbsip.sqlite"  # big working file, never committed
PROG = os.path.join(OUT, "_progress.json")
TRADES = os.path.join(OUT, "trades.csv")
START = dt.date(2016, 1, 4)
NY = "America/New_York"


def log(*a):
    print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def _prog():
    try:
        return json.load(open(PROG))
    except Exception:
        return {}


def _save_prog(p):
    os.makedirs(OUT, exist_ok=True)
    json.dump(p, open(PROG + ".tmp", "w"), indent=1)
    os.replace(PROG + ".tmp", PROG)


def _data():
    from alpaca.data.historical import StockHistoricalDataClient
    return StockHistoricalDataClient(os.environ["ALPACA_KEY"], os.environ["ALPACA_SECRET"])


def _market_hours():
    """True from 7:30 to 16:45 on a trading day: the live bot needs the Alpaca request budget then, so this job pauses."""
    now = pd.Timestamp.now(tz=NY)
    if now.weekday() >= 5:
        return False
    try:
        import market
        if market.is_holiday(now.date()):
            return False
    except Exception:
        pass
    return dt.time(7, 30) <= now.time() < dt.time(16, 45)


def _get(cl, syms, tf, start, end, tries=4):
    if _market_hours():
        log("market hours: pausing until after the close")
        sys.exit(0)
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.enums import Adjustment, DataFeed
    for k in range(tries):
        try:
            req = StockBarsRequest(symbol_or_symbols=syms, timeframe=tf, start=start, end=end,
                                   adjustment=Adjustment.SPLIT, feed=DataFeed.SIP)
            df = cl.get_stock_bars(req).df
            time.sleep(0.35)
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.reset_index()
            df["ts"] = pd.to_datetime(df["timestamp"]).dt.tz_convert(NY)
            return df
        except Exception as e:
            log("bars retry", k, repr(e)[:160])
            time.sleep(10 * (k + 1))
    return None


def step_universe(p):
    """Every active, tradable US-listed symbol (plain tickers only)."""
    if p.get("universe"):
        return p["universe"]
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import GetAssetsRequest
    from alpaca.trading.enums import AssetStatus, AssetClass
    tc = TradingClient(os.environ["ALPACA_KEY"], os.environ["ALPACA_SECRET"], paper=True)
    assets = tc.get_all_assets(GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY))
    ex = {"NYSE", "NASDAQ", "ARCA", "AMEX", "BATS"}
    u = sorted({a.symbol for a in assets if a.tradable and str(getattr(a.exchange, "value", a.exchange)) in ex
                and a.symbol.isalpha() and len(a.symbol) <= 5})
    p["universe"] = u
    _save_prog(p)
    log("universe", len(u))
    return u


def step_daily(p, cl, u):
    """Daily bars -> per symbol per day: open, prior 14-day ATR, prior 14-day average volume. Keep only days that pass
    the price/volume/ATR screen (that's all the later steps need)."""
    from alpaca.data.timeframe import TimeFrame
    db = sqlite3.connect(DB)
    db.execute("create table if not exists elig (day text, sym text, open real, atr real, avgv real, primary key(day, sym))")
    done = set(p.get("daily_done", []))
    chunks = [u[i:i + 100] for i in range(0, len(u), 100)]
    for n, ch in enumerate(chunks):
        key = ch[0]
        if key in done:
            continue
        df = _get(cl, ch, TimeFrame.Day, dt.datetime(2015, 11, 1), dt.datetime.now() - dt.timedelta(days=1))
        if df is None:
            log("daily chunk failed", key); continue
        rows = []
        for s, g in (df.groupby("symbol") if len(df) else []):
            g = g.sort_values("ts")
            pc = g.close.shift()
            tr = pd.concat([g.high - g.low, (g.high - pc).abs(), (g.low - pc).abs()], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().shift()
            av = g.volume.rolling(14).mean().shift()
            ok = (g.open > 5) & (av >= 1e6) & (atr > 0.5)
            for d, o, a, v in zip(g.ts[ok].dt.strftime("%Y-%m-%d"), g.open[ok], atr[ok], av[ok]):
                rows.append((d, s, float(o), float(a), float(v)))
        db.executemany("insert or replace into elig values (?,?,?,?,?)", rows)
        db.commit()
        done.add(key)
        p["daily_done"] = sorted(done)
        _save_prog(p)
        log(f"daily {n + 1}/{len(chunks)}: {len(rows)} eligible stock-days")
    db.close()
    p["daily_complete"] = True
    _save_prog(p)


def _sim(bars, side, level, stop_dist):
    """bars: 1-minute bars from 9:35 to 16:00, sorted. Returns (entry, exit, reason, entry_time) or None."""
    e = None
    for ts, o, h, l, c in zip(bars.ts, bars.open, bars.high, bars.low, bars.close):
        if e is None:
            if side == "long" and h > level:
                e = max(level, o); s = e - stop_dist; et = ts
                if l <= s:
                    return e, s, "stop_same_bar", et
            elif side == "short" and l < level:
                e = min(level, o); s = e + stop_dist; et = ts
                if h >= s:
                    return e, s, "stop_same_bar", et
            continue
        if side == "long" and l <= s:
            return e, min(s, o), "stop", et
        if side == "short" and h >= s:
            return e, max(s, o), "stop", et
    if e is None:
        return None
    return e, float(bars.close.iloc[-1]), "close", et


def step_days(p, cl):
    """For each trading day: first 5-minute bar for every eligible stock -> relative volume -> top 20 -> 1-minute replay."""
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    db = sqlite3.connect(DB)
    days = [r[0] for r in db.execute("select distinct day from elig where day >= ? order by day", (str(START),))]
    hist = defaultdict(lambda: deque(maxlen=14))  # first-5-minute volumes, per symbol
    # rebuild the 14-day history from saved first-5 bars so a restart resumes exactly
    db.execute("create table if not exists first5 (day text, sym text, v real, primary key(day, sym))")
    last = p.get("days_done_through", "")
    for d, s, v in db.execute("select day, sym, v from first5 where day <= ? order by day", (last,)):
        hist[s].append(v)
    os.makedirs(OUT, exist_ok=True)
    new_file = not os.path.exists(TRADES)
    fh = open(TRADES, "a")
    if new_file:
        fh.write("day,sym,side,relvol,atr,open5,level,entry,exit,reason,entry_time,ret\n")
    for d in days:
        if d <= last:
            continue
        elig = {s: (o, a) for s, o, a in db.execute("select sym, open, atr from elig where day = ?", (d,))}
        if not elig:
            continue
        t0 = pd.Timestamp(d + " 09:30", tz=NY)
        syms = sorted(elig)
        f5 = []
        for i in range(0, len(syms), 400):
            df = _get(cl, syms[i:i + 400], TimeFrame(5, TimeFrameUnit.Minute), t0.to_pydatetime(),
                      (t0 + pd.Timedelta(minutes=5)).to_pydatetime())
            if df is None:
                log("first5 failed", d); f5 = None; break
            if len(df):
                f5.append(df[df.ts == t0])
        if f5 is None:
            fh.close(); db.close(); return False  # retry this day next run
        f5 = pd.concat(f5) if f5 else pd.DataFrame()
        cands = []
        for r in f5.itertuples():
            h = hist[r.symbol]
            rv = r.volume / (sum(h) / len(h)) if len(h) == 14 and sum(h) > 0 else None
            if rv and rv >= 1 and r.close != r.open:
                cands.append((rv, r))
        db.executemany("insert or replace into first5 values (?,?,?)", [(d, r.symbol, float(r.volume)) for r in f5.itertuples()])
        for r in f5.itertuples():
            hist[r.symbol].append(r.volume)
        top = sorted(cands, key=lambda x: -x[0])[:20]
        if top:
            m1 = _get(cl, [r.symbol for _, r in top], TimeFrame.Minute, (t0 + pd.Timedelta(minutes=5)).to_pydatetime(),
                      (t0 + pd.Timedelta(minutes=390)).to_pydatetime())
            if m1 is None:
                fh.close(); db.close(); return False
            for rv, r in top:
                side = "long" if r.close > r.open else "short"
                level = r.high if side == "long" else r.low
                atr = elig[r.symbol][1]
                bars = m1[m1.symbol == r.symbol].sort_values("ts") if len(m1) else m1
                if not len(bars):
                    continue
                res = _sim(bars, side, level, 0.10 * atr)
                if not res:
                    continue
                e, x, why, et = res
                ret = (x / e - 1) if side == "long" else (e / x - 1)
                fh.write(f"{d},{r.symbol},{side},{rv:.2f},{atr:.3f},{r.open:.4f},{level:.4f},{e:.4f},{x:.4f},{why},"
                         f"{et.strftime('%H:%M')},{ret:.6f}\n")
        fh.flush()
        db.commit()
        p["days_done_through"] = d  # saved every day, so a restart never writes a day's trades twice
        _save_prog(p)
        if d[8:10] <= "07":
            log("day", d, "candidates", len(cands), "traded", len(top))
    fh.close(); db.close()
    p["complete"] = True
    _save_prog(p)
    return True


def _locked():
    lk = os.path.join(OUT, "_lock")
    if os.path.exists(lk):
        try:
            os.kill(int(open(lk).read().strip()), 0)
            return True
        except Exception:
            pass
    os.makedirs(OUT, exist_ok=True)
    open(lk, "w").write(str(os.getpid()))
    return False


if __name__ == "__main__":
    if _locked():
        sys.exit(0)
    p = _prog()
    if p.get("complete"):
        sys.exit(0)
    cl = _data()
    u = step_universe(p)
    if not p.get("daily_complete"):
        step_daily(p, cl, u)
    step_days(p, cl)
