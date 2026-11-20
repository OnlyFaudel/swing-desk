"""Prices, indicators, earnings dates, market clock."""
import datetime as dt
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import yfinance as yf

ET = ZoneInfo("America/New_York")
INTRADAY = {}  # latest 5-minute bars per ticker (used by the simulator to fill resting orders)


def now_et():
    return dt.datetime.now(ET)


def market_open(t=None):
    t = t or now_et()
    return t.weekday() < 5 and dt.time(9, 35) <= t.time() <= dt.time(15, 58)


def rsi(c, n):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def indicators(df):
    df = df.copy()
    df["sma20"] = df.Close.rolling(20).mean()
    df["sma50"] = df.Close.rolling(50).mean()
    df["sma200"] = df.Close.rolling(200).mean()
    df["rsi2"] = rsi(df.Close, 2)
    df["rsi14"] = rsi(df.Close, 14)
    pc = df.Close.shift()
    tr = pd.concat([df.High - df.Low, (df.High - pc).abs(), (df.Low - pc).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    df["hi20"] = df.High.rolling(20).max()
    df["vol20"] = df.Volume.rolling(20).mean()
    return df


_DAILY = {"t": 0, "key": None, "data": None}
LIVE = {}  # ticker -> (price, epoch seconds) from the real-time stream (hawk mode)


def fetch(tickers):
    """Daily history (cached 3 hours) + today's bar rebuilt from 5-minute data (Yahoo leaves it blank).
    In hawk mode a cycle runs every minute, so the 2-year history is not re-downloaded each time."""
    import time
    allt = list(tickers)
    key = tuple(sorted(allt))
    if _DAILY["data"] is None or _DAILY["key"] != key or time.time() - _DAILY["t"] > 3 * 3600:
        raw = yf.download(allt, period="2y", auto_adjust=True, progress=False)
        _DAILY.update(t=time.time(), key=key, data={t: raw.xs(t, axis=1, level=1).dropna()[["Open", "High", "Low", "Close", "Volume"]] for t in allt})
    data = {t: df.copy() for t, df in _DAILY["data"].items()}
    intra = yf.download(allt, period="1d", interval="5m", auto_adjust=True, progress=False)
    INTRADAY.clear()
    last = {}
    for t in allt:
        try:
            b = intra.xs(t, axis=1, level=1).dropna()
        except KeyError:
            b = pd.DataFrame()
        if not b.empty:
            INTRADAY[t] = b
            day = pd.Timestamp(b.index[-1].date())
            row = [b.Open.iloc[0], b.High.max(), b.Low.min(), b.Close.iloc[-1], b.Volume.sum()]
            if day > data[t].index[-1]:
                data[t].loc[day] = row
            elif day == data[t].index[-1]:
                data[t].loc[day] = row
            last[t] = float(b.Close.iloc[-1])
        else:
            last[t] = float(data[t].Close.iloc[-1])
        lv = LIVE.get(t)
        if lv and time.time() - lv[1] < 120:  # a fresher price from the live stream wins
            last[t] = lv[0]
    return {t: indicators(df) for t, df in data.items()}, last


def snapshot(df, price):
    """Numbers the technical analyst sees."""
    r = df.iloc[-1]
    prev = df.Close.iloc[-2]
    f = lambda x: None if pd.isna(x) else round(float(x), 2)
    return {"price": round(price, 2), "change_today_pct": f((price / prev - 1) * 100),
            "sma20": f(r.sma20), "sma50": f(r.sma50), "sma200": f(r.sma200),
            "above_sma50": bool(price > r.sma50), "rsi2": f(r.rsi2), "rsi14": f(r.rsi14),
            "atr_pct": f(r.atr / price * 100), "pct_below_20d_high": f((1 - price / r.hi20) * 100),
            "volume_vs_20d_avg": f(r.Volume / r.vol20) if r.vol20 else None,
            "change_5d_pct": f((price / df.Close.iloc[-6] - 1) * 100),
            "change_20d_pct": f((price / df.Close.iloc[-21] - 1) * 100)}


_earn_cache = {}


def next_earnings(t):
    if t in _earn_cache:
        return _earn_cache[t]
    d = None
    try:
        cal = yf.Ticker(t).calendar
        ds = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if ds:
            future = [x for x in ds if x >= dt.date.today()]
            d = str(future[0]) if future else None
    except Exception:
        pass
    _earn_cache[t] = d
    return d


def trading_days_until(date_str):
    if not date_str:
        return None
    return int(np.busday_count(dt.date.today(), dt.date.fromisoformat(date_str)))


_HOURLY = {"t": 0, "data": {}}


def fetch_hourly(tickers, max_age_min=20):
    """Hourly bars (last ~60 days), cached for max_age_min minutes."""
    import time
    if time.time() - _HOURLY["t"] < max_age_min * 60 and _HOURLY["data"]:
        return _HOURLY["data"]
    raw = yf.download(list(tickers), period="60d", interval="1h", auto_adjust=True, progress=False)
    out = {}
    for t in tickers:
        try:
            x = raw.xs(t, axis=1, level=1).dropna()
            x.index = x.index.tz_convert("America/New_York")
            out[t] = x
        except Exception:
            pass
    _HOURLY.update(t=time.time(), data=out)
    return out
