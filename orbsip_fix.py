"""Second pass for orbsip.py (2026-11-27). 43% of replayed trades touched both the entry and the stop inside the same
1-minute bar; the first pass counted all of them as stopped (worst case), and that single assumption decides whether
the strategy loses (all counted as stops) or wins (+0.5R a trade if they are dropped). This pass settles each one with
the actual trade ticks of that minute: was the stop hit after the breakout fill, or not? Trades that survive the
minute are then followed on 1-minute bars to the stop or the close, exactly as in the first pass.

Output: data/orbsip/same_minute_resolved.csv (day, sym, side, entry, exit, reason, ret). Resumable; pauses during
market hours like orbsip.py.
"""
import os, sys, json, time, datetime as dt
import pandas as pd
import orbsip

OUT = orbsip.OUT
RES = os.path.join(OUT, "same_minute_resolved.csv")
PROG = os.path.join(OUT, "_progress_fix.json")
NY = orbsip.NY


def _ticks(cl, sym, start, end, tries=4):
    from alpaca.data.requests import StockTradesRequest
    from alpaca.data.enums import DataFeed
    if orbsip._market_hours():
        orbsip.log("market hours: pausing until after the close")
        sys.exit(0)
    for k in range(tries):
        try:
            df = cl.get_stock_trades(StockTradesRequest(symbol_or_symbols=sym, start=start, end=end, feed=DataFeed.SIP)).df
            time.sleep(0.3)
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.reset_index().sort_values("timestamp")
            return df[["timestamp", "price"]]
        except Exception as e:
            orbsip.log("ticks retry", k, repr(e)[:160])
            time.sleep(10 * (k + 1))
    return None


def resolve(ticks, side, level, stop):
    """Walk the minute's ticks: fill at the first print through the level, then stopped if a later print reaches the
    stop. Returns (filled, stopped, fill_price)."""
    fill = None
    for p in ticks.price:
        if fill is None:
            if (side == "long" and p > level) or (side == "short" and p < level):
                fill = p
            continue
        if (side == "long" and p <= stop) or (side == "short" and p >= stop):
            return True, True, fill
    return fill is not None, False, fill


def main():
    from alpaca.data.timeframe import TimeFrame
    t = pd.read_csv(orbsip.TRADES).drop_duplicates(["day", "sym"])
    amb = t[t.reason == "stop_same_bar"].sort_values(["day", "sym"])
    try:
        prog = json.load(open(PROG))
    except Exception:
        prog = {}
    done_through = prog.get("done_through", "")
    cl = orbsip._data()
    new = not os.path.exists(RES)
    fh = open(RES, "a")
    if new:
        fh.write("day,sym,side,entry,exit,reason,ret\n")
    for day, g in amb.groupby("day"):
        if day <= done_through:
            continue
        t0 = pd.Timestamp(day + " 09:30", tz=NY)
        bars = orbsip._get(cl, sorted(g.sym), TimeFrame.Minute, (t0 + pd.Timedelta(minutes=5)).to_pydatetime(),
                           (t0 + pd.Timedelta(minutes=390)).to_pydatetime())
        if bars is None:
            break
        for r in g.itertuples():
            m0 = pd.Timestamp(f"{day} {r.entry_time}", tz=NY)
            ticks = _ticks(cl, r.sym, m0.to_pydatetime(), (m0 + pd.Timedelta(minutes=1)).to_pydatetime())
            if ticks is None:
                fh.close(); return
            stop_dist = 0.10 * r.atr
            # the first pass filled at max(level, bar open); keep that fill so results stay comparable
            stop = r.entry - stop_dist if r.side == "long" else r.entry + stop_dist
            filled, stopped, _ = resolve(ticks, r.side, r.level, stop) if len(ticks) else (True, True, None)
            if stopped or not filled:
                x, why = stop, "stop_same_minute_ticks"
            else:
                b = bars[(bars.symbol == r.sym) & (bars.ts > m0)].sort_values("ts") if len(bars) else bars
                x, why = (float(b.close.iloc[-1]) if len(b) else r.entry), "close"
                for o, h, l in zip(b.open, b.high, b.low):
                    if r.side == "long" and l <= stop:
                        x, why = min(stop, o), "stop"; break
                    if r.side == "short" and h >= stop:
                        x, why = max(stop, o), "stop"; break
            ret = (x / r.entry - 1) if r.side == "long" else (r.entry / x - 1)
            fh.write(f"{day},{r.sym},{r.side},{r.entry:.4f},{x:.4f},{why},{ret:.6f}\n")
        fh.flush()
        prog["done_through"] = day
        json.dump(prog, open(PROG + ".tmp", "w")); os.replace(PROG + ".tmp", PROG)
        if day[8:10] <= "03":
            orbsip.log("resolved through", day)
    else:
        prog["complete"] = True
        json.dump(prog, open(PROG + ".tmp", "w")); os.replace(PROG + ".tmp", PROG)
    fh.close()


if __name__ == "__main__":
    lk = os.path.join(OUT, "_lock_fix")
    if os.path.exists(lk):
        try:
            os.kill(int(open(lk).read().strip()), 0)
            sys.exit(0)
        except Exception:
            pass
    open(lk, "w").write(str(os.getpid()))
    main()
