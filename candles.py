"""15-minute candles for day-trading research (owner's idea, 2026-11-26).

intraday.py keeps one summary row per stock per day; testing opening-range breakouts or VWAP bounces needs the candles
themselves. 1-minute bars for 10 years are far too big for the repo, so this saves 15-minute candles (26 per day) for a
focused list, regular session only, built from Alpaca minute bars.

Run on the server (it has the Alpaca keys):  python candles.py backfill   (once, ~30-60 min, resumable)
                                            python candles.py daily      (after each close)
Output: data/candles15/YYYY-MM.csv.gz  columns t, ts (bar start, New York time), open, high, low, close, volume, vwap
"""
import os, sys, json, time, datetime as dt
import pandas as pd
import intraday

FREQ = int(os.environ.get("CANDLE_MIN", "15"))
OUT = "data/candles15" if FREQ == 15 else f"data/candles{FREQ}"
PROG = os.path.join(OUT, "_progress.json")
COLS = ["t", "ts", "open", "high", "low", "close", "volume", "vwap"]
LIST = ["CCJ", "NXE", "UEC", "DNN", "UUUU", "LEU", "BWXT", "CEG", "VST", "TLN", "OKLO", "SMR", "NNE", "SPY"]
if FREQ != 15:  # finer candles are big: only the most-traded names (tight spreads, where day trading has a chance)
    LIST = ["CCJ", "VST", "CEG", "BWXT", "LEU", "OKLO", "SPY"]


def to15(df, t):
    if df is None or df.empty or "ts" not in df:
        return pd.DataFrame(columns=COLS)
    tt = df.ts.dt.time
    df = df[(tt >= dt.time(9, 30)) & (tt < dt.time(16, 0))].copy()
    if df.empty:
        return pd.DataFrame(columns=COLS)
    df["pv"] = df.close * df.volume
    g = df.set_index("ts").resample(f"{FREQ}min", origin="start_day", offset="30min", label="left", closed="left")
    c = pd.DataFrame({"open": g.open.first(), "high": g.high.max(), "low": g.low.min(), "close": g.close.last(),
                      "volume": g.volume.sum(), "pv": g.pv.sum()}).dropna(subset=["open"])
    c["vwap"] = (c.pv / c.volume.where(c.volume > 0)).round(4)
    c = c.drop(columns="pv").reset_index()
    c["t"] = t
    c["ts"] = c.ts.dt.strftime("%Y-%m-%d %H:%M")
    return c[COLS]


def _write(frames):
    if not frames:
        return
    new = pd.concat(frames)
    if new.empty:
        return
    os.makedirs(OUT, exist_ok=True)
    for month, part in new.groupby(new.ts.str[:7]):
        p = os.path.join(OUT, f"{month}.csv.gz")
        old = pd.read_csv(p) if os.path.exists(p) else pd.DataFrame(columns=COLS)
        allr = pd.concat([old, part]).drop_duplicates(["t", "ts"], keep="last").sort_values(["ts", "t"])
        allr.to_csv(p + ".tmp", index=False, compression="gzip")
        os.replace(p + ".tmp", p)


def _prog():
    try:
        return json.load(open(PROG))
    except Exception:
        return {}


def pull(tickers, start, end, resume=True):
    cl = intraday._client()
    prog = _prog() if resume else {}
    for t in tickers:
        if resume and (prog.get(t) or {}).get("done"):
            continue
        frames, feed, fails, err, y = [], "sip", 0, "", start
        while y < end:
            y2 = min(end, y + dt.timedelta(days=60))
            for attempt in range(3):
                try:
                    try:
                        df = intraday._bars(cl, t, y, y2, feed)
                    except Exception as e:
                        if feed == "sip" and ("subscription" in str(e).lower() or "403" in str(e) or "forbidden" in str(e).lower()):
                            feed = "iex"
                            df = intraday._bars(cl, t, y, y2, feed)
                        else:
                            raise
                    frames.append(to15(df, t))
                    break
                except Exception as e:
                    err = repr(e)[:200]
                    print("candles", t, y, err, flush=True)
                    if attempt == 2:
                        fails += 1
                    time.sleep(5 * (attempt + 1))
            y = y2
            time.sleep(0.35)
            if len(frames) >= 12:  # write every ~2 years so memory stays small on the e2-micro
                _write(frames); frames = []
        _write(frames)
        if resume:
            prog[t] = {"done": fails <= 2, "failed_chunks": fails, "feed": feed, "err": err}
            json.dump(prog, open(PROG + ".tmp", "w")); os.replace(PROG + ".tmp", PROG)
        print(f"candles {t}: done ({feed}), {fails} failed chunks {err}", flush=True)
    if resume:
        prog["_complete"] = all((prog.get(t) or {}).get("done") for t in tickers)
        json.dump(prog, open(PROG + ".tmp", "w")); os.replace(PROG + ".tmp", PROG)


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
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if _locked():
        sys.exit(0)
    now = dt.datetime.now(dt.timezone.utc)
    end = (now - dt.timedelta(minutes=20)).replace(second=0, microsecond=0)  # SIP history needs to be 15+ min old
    if mode == "backfill":
        pull(LIST, dt.datetime(2016, 1, 1, tzinfo=dt.timezone.utc), end, resume=True)
    else:
        pull(LIST, end - dt.timedelta(days=4), end, resume=False)
