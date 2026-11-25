"""After-hours watcher, "Night Watch" (owner, 2026-11-24: "why not add a bot for the after hours?").

No money yet. From 16:20 to 20:00 ET on trading days it checks our stocks (and anything we hold) every 20 minutes. A move of
3%+ from the 4 PM close gets logged with the headlines behind it and posted to the team; 5%+, or 3%+ on something we hold,
also buzzes the owner's phone. The next day it scores each case: did the after-hours move hold at the 9:35 price and at the
close, or did it reverse? That record goes to every agent in the morning and is the evidence for (or against) ever trading
after hours. The historical version of the same test runs on the minute data (intraday.py, pre_px / ah_px columns).
"""
import datetime as dt

MIN_MOVE, BIG_MOVE = 3.0, 5.0


def _fetch(tickers):
    import yfinance as yf
    raw = yf.download(sorted(set(tickers)), period="1d", interval="5m", prepost=True, progress=False, auto_adjust=False)
    out = {}
    if raw is None or raw.empty:
        return out
    for t in set(tickers):
        try:
            c, v = raw["Close"][t].dropna(), raw["Volume"][t].fillna(0)
        except Exception:
            continue
        if c.empty:
            continue
        tm = c.index.tz_convert("America/New_York").time
        reg, ah = c[[x < dt.time(16, 0) and x >= dt.time(9, 30) for x in tm]], c[[x >= dt.time(16, 0) for x in tm]]
        if reg.empty or ah.empty:
            continue
        vt = v.reindex(c.index).fillna(0)
        out[t] = {"close": float(reg.iloc[-1]), "ah_px": float(ah.iloc[-1]),
                  "ah_vol": int(vt[[x >= dt.time(16, 0) for x in tm]].sum()), "day_vol": int(vt[[dt.time(9, 30) <= x < dt.time(16, 0) for x in tm]].sum())}
    return out


def watch(st, today, now, tickers, held, notify, post):
    """16:20-20:00 ET, every 20 minutes."""
    if not (dt.time(16, 20) <= now.time() <= dt.time(20, 0)):
        return
    slot = f"nightwatch{now.hour}{now.minute // 20}:{today}"
    if st["flags"].get(slot):
        return
    st["flags"][slot] = True
    try:
        snap = _fetch(list(tickers) + list(held))
    except Exception as e:
        print("night watch", e)
        return
    log = st.setdefault("ah_watch", [])
    for t, s in snap.items():
        mv = (s["ah_px"] / s["close"] - 1) * 100
        e = next((x for x in log if x["date"] == str(today) and x["t"] == t), None)
        if e:  # keep the latest after-hours price for cases already logged
            e.update({"ah_px": round(s["ah_px"], 4), "ah_move": round(mv, 2), "ah_vol": s["ah_vol"]})
            continue
        if abs(mv) < MIN_MOVE:  # (Yahoo often reports 0 after-hours volume even when trades happened, so no volume filter)
            continue
        heads = [f["title"] for f in st.get("news_feed", []) if f.get("ticker") == t][-4:]
        e = {"date": str(today), "t": t, "close": round(s["close"], 4), "ah_px": round(s["ah_px"], 4), "ah_move": round(mv, 2),
             "ah_vol": s["ah_vol"], "vol_share_pct": round(100 * s["ah_vol"] / max(1, s["day_vol"]), 1), "first_seen": now.strftime("%H:%M"),
             "headlines": heads, "held": t in held}
        log.append(e)
        why = f" Latest headlines: {' | '.join(heads[-2:])}" if heads else " No headline on file for it yet; the news collector keeps looking."
        post(f"After hours: {t} is {mv:+.1f}% from the 4 PM close (${s['close']:.2f} -> ${s['ah_px']:.2f}), on {s['ah_vol']:,} shares reported.{why} Tomorrow I'll score whether it held at 9:35 and at the close. "
             f"{summary(st)['line']}", [t])
        if abs(mv) >= BIG_MOVE or (t in held and abs(mv) >= MIN_MOVE):
            notify(f"After hours: {t} {mv:+.1f}%", f"${s['close']:.2f} at 4 PM -> ${s['ah_px']:.2f} now." + (" We hold it." if t in held else "")
                   + (f" {heads[-1][:120]}" if heads else ""))
    del log[:-500]


def score(st, today, now, prices, cclock):
    """Next session: price at 9:35 and the close vs the after-hours price."""
    for e in st.get("ah_watch", []):
        if e["date"] >= str(today) or e.get("close_next") is not None or not prices.get(e["t"]):
            continue
        px = float(prices[e["t"]])
        if e.get("px935") is None and now.time() >= dt.time(9, 35):
            e["px935"] = round(px, 4)
            e["held_at_935"] = (px - e["close"]) * (e["ah_px"] - e["close"]) > 0 and abs(px / e["close"] - 1) >= abs(e["ah_move"]) / 200
        if cclock >= dt.time(15, 55):
            e["close_next"] = round(px, 4)
            e["next_day_pct_from_ah"] = round((px / e["ah_px"] - 1) * 100, 2)  # after the after-hours price: kept going (+ same sign) or gave back
            e["kept_going"] = (px - e["ah_px"]) * (e["ah_px"] - e["close"]) > 0


def summary(st):
    done = [e for e in st.get("ah_watch", []) if e.get("close_next") is not None]
    if not done:
        return {"line": "First after-hours cases on record; no score yet.", "n": 0}
    held = sum(1 for e in done if e.get("held_at_935"))
    kept = sum(1 for e in done if e.get("kept_going"))
    return {"n": len(done), "held_at_935": held, "kept_going_next_day": kept,
            "line": f"Record so far: {len(done)} scored; the move held at 9:35 in {held} and kept going through the next close in {kept}."}


def last_night(st, today):
    """For the agents' morning: last night's after-hours moves."""
    prev = [e for e in st.get("ah_watch", []) if e["date"] < str(today)]
    if not prev:
        return None
    d = max(e["date"] for e in prev)
    return {"date": d, "moves": [f"{e['t']} {e['ah_move']:+.1f}% after hours (${e['close']} -> ${e['ah_px']})" for e in prev if e["date"] == d],
            "record": summary(st)["line"]}
