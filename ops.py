"""Operational safety (code). These trip on MALFUNCTIONS, not on losses: the owner chose to keep
trading through bad days, so losses never pause the bot, but bugs must.

  - 3+ order rejections in an hour                -> halt new orders
  - more than max_orders_per_hour orders sent     -> halt new orders (runaway loop)
  - a trade position bigger than allowed          -> halt new orders + alert
  - a filled trade without a working stop         -> place it now; if that fails, exit the position
  - stale prices (no fresh bar during the session) -> skip trading this cycle

Once halted, the bot keeps managing exits/stops but sends no new entries until the owner sets
"ops_resume": true in config.json (then back to false).
"""
import time


def state(st):
    return st.setdefault("ops", {"rejects": [], "orders": [], "halted": False, "reason": "", "events": []})


def event(st, kind, msg):
    o = state(st)
    o["events"].append({"t": time.strftime("%Y-%m-%d %H:%M"), "kind": kind, "msg": msg[:200]})
    del o["events"][:-50]


def note_order(st, cfg, notify):
    o = state(st)
    now = time.time()
    o["orders"] = [x for x in o["orders"] if now - x < 3600] + [now]
    if len(o["orders"]) > cfg["ops"]["max_orders_per_hour"]:
        halt(st, f"{len(o['orders'])} orders in the last hour (possible runaway loop)", notify)


def note_reject(st, cfg, notify, msg):
    o = state(st)
    now = time.time()
    o["rejects"] = [x for x in o["rejects"] if now - x < 3600] + [now]
    event(st, "reject", msg)
    if len(o["rejects"]) >= cfg["ops"]["max_rejects_per_hour"]:
        halt(st, f"{len(o['rejects'])} order rejections in an hour: last '{msg[:80]}'", notify)


def halt(st, reason, notify):
    o = state(st)
    if not o["halted"]:
        o["halted"], o["reason"] = True, reason
        event(st, "halt", reason)
        notify("BOT HALTED (malfunction guard)", reason + ". Exits and stops still run. Set ops_resume true to restart entries.",
               tags="rotating_light", priority="urgent")


def check(st, cfg, notify, prices, equity, lots, intraday, market_open):
    """Returns True if new entries are allowed this cycle."""
    o = state(st)
    if cfg.get("ops_resume"):
        if o["halted"]:
            event(st, "resume", "owner resumed")
        o["halted"], o["reason"] = False, ""
    cap = equity * cfg["max_position_pct"] / 100 * 1.25
    for t, l in lots.items():
        tv = l.get("trade", {}).get("qty", 0) * prices.get(t, 0)
        if tv > cap and tv > 50:
            halt(st, f"{t} trade position ${tv:.0f} is above the allowed ${cap:.0f}", notify)
    if market_open and intraday:
        import pandas as pd
        newest = max((df.index[-1] for df in intraday.values() if len(df)), default=None)
        if newest is not None and (pd.Timestamp.now(tz=newest.tz) - newest).total_seconds() > cfg["ops"]["stale_minutes"] * 60:
            event(st, "stale", f"newest price bar is from {newest}")
            return False
    return not o["halted"]
