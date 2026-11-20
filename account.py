"""Account Officer (code). The bot's own books, independent of how big the broker account is
(Alpaca paper starts at $100k; the bot only ever uses capital_cap).

Each ticker has two lots: 'core' (long-term) and 'trade' (one active swing trade at a time).
Every order carries a tag in its client_order_id so fills are booked to the right lot:
  core / coreadj    core buys/sells        lvl / dip / news   trade entries
  stop / tp / exit  trade exits
Also: settled cash (T+1, no good-faith violations in a cash account), loss brakes,
wash-sale flags, short-term gains estimate.
"""
import datetime as dt

COST = 0.0


def new_book(cash):
    return {"cash": cash, "lots": {}, "trades": [], "equity": [], "peak": cash, "unsettled": [],
            "weeks": [], "week": None, "week_start": cash, "day": None, "day_start": cash,
            "killed": False, "wash_flags": [], "buys_log": [], "realized_st": 0.0, "core_w": {}}


def lot(book, t, kind):
    return book["lots"].setdefault(t, {}).setdefault(kind, {"qty": 0.0, "cost": 0.0})


def tag_of(client_id):
    parts = (client_id or "").split("-")
    return parts[1] if len(parts) > 2 else "unknown"


def equity(book, prices):
    v = book["cash"]
    for t, lots in book["lots"].items():
        for l in lots.values():
            v += l["qty"] * prices.get(t, (l["cost"] / l["qty"]) if l["qty"] else 0)
    return v


def core_value(book, prices):
    return sum(l.get("core", {}).get("qty", 0) * prices.get(t, 0) for t, l in book["lots"].items())


def trade_value(book, prices):
    return sum(l.get("trade", {}).get("qty", 0) * prices.get(t, 0) for t, l in book["lots"].items())


def settled_cash(book, today):
    pending = sum(a for a, d in book["unsettled"] if d > str(today))
    book["unsettled"] = [[a, d] for a, d in book["unsettled"] if d > str(today)]
    return max(0.0, book["cash"] - pending)


def next_session(today):
    import exchange_calendars as xc
    import pandas as pd
    cal = xc.get_calendar("XNYS")
    s = cal.sessions_in_range(pd.Timestamp(today) + pd.Timedelta(days=1), pd.Timestamp(today) + pd.Timedelta(days=10))
    return str(s[0].date()) if len(s) else str(today + dt.timedelta(days=1))


def apply_fill(book, f, today, meta=None):
    """Book one broker fill. Returns a closed-trade record if a trade lot was closed."""
    t, side, q, px = f["symbol"], f["side"], float(f["qty"]), float(f["fill_price"])
    tag = tag_of(f.get("client_id"))
    kind = "core" if tag.startswith("core") else "trade"
    L = lot(book, t, kind)
    if side == "buy":
        book["cash"] -= q * px
        L["qty"] += q
        L["cost"] += q * px
        book["buys_log"].append([t, str(today), kind])
        book["buys_log"] = book["buys_log"][-200:]
        if kind == "trade" and meta:
            L.update({k: v for k, v in meta.items() if k not in ("qty", "cost")})
            L.setdefault("opened", str(today))
            L.setdefault("entry_time", f.get("filled_at"))
            L["entry"] = round(px, 2)
        return None
    # sell
    q = min(q, L["qty"]) if L["qty"] > 0 else q
    avg = L["cost"] / L["qty"] if L["qty"] else px
    proceeds = q * px
    pnl = proceeds - avg * q
    book["cash"] += proceeds
    book["unsettled"].append([proceeds, next_session(today)])
    book["realized_st"] = round(book["realized_st"] + pnl, 2)
    L["qty"] = round(L["qty"] - q, 6)
    L["cost"] = max(0.0, L["cost"] - avg * q)
    rec = None
    if kind == "trade":
        rec = {"ticker": t, "setup": L.get("setup", "?"), "by": L.get("by", "?"), "entry_time": L.get("entry_time"),
               "entry": round(avg, 2), "exit_time": f.get("filled_at"), "exit": round(px, 2), "dollars": round(avg * q, 2),
               "pnl": round(pnl, 2), "ret": round((px / avg - 1) * 100, 2), "why_in": L.get("why", ""),
               "why_out": {"stop": "stop loss hit", "tp": "target hit"}.get(tag, L.get("exit_reason") or tag),
               "risk_pct": round((avg - L["stop"]) / avg * 100, 2) if L.get("stop") and avg > L["stop"] else None,
               "stop": L.get("stop"), "target": L.get("target"), "zone": L.get("zone")}
        book["trades"].append(rec)
        if L["qty"] <= 1e-6:
            book["lots"][t]["trade"] = {"qty": 0.0, "cost": 0.0}
    # wash sale: a loss with a buy of the same stock within 30 days (core buys count too)
    if pnl < 0:
        recent = [b for b in book["buys_log"] if b[0] == t and (today - dt.date.fromisoformat(b[1])).days <= 30
                  and not (b[1] == str(today) and b[2] == kind)]
        if recent:
            book["wash_flags"].append({"ticker": t, "date": str(today), "loss": round(pnl, 2),
                                       "note": "Loss likely disallowed now and added to the cost basis of shares you still hold (not lost, deferred)."})
            book["wash_flags"] = book["wash_flags"][-100:]
    return rec


def roll(book, prices, today):
    eq = equity(book, prices)
    wk = "%d-W%02d" % today.isocalendar()[:2]
    if book["week"] != wk:
        if book["week"] is not None:
            book["weeks"].append({"week": book["week"], "start": round(book["week_start"], 2), "end": round(eq, 2),
                                  "ret_pct": round((eq / book["week_start"] - 1) * 100, 2)})
        book["week"], book["week_start"] = wk, eq
    if book["day"] != str(today):
        book["day"], book["day_start"] = str(today), eq
    book["peak"] = max(book["peak"], eq)
    return eq


def brakes(book, prices, cfg, today):
    eq = roll(book, prices, today)
    b = cfg["brakes"]
    day = (eq / book["day_start"] - 1) * 100
    week = (eq / book["week_start"] - 1) * 100
    dd = (eq / book["peak"] - 1) * 100
    if b.get("kill_drawdown_pct") is not None and dd <= b["kill_drawdown_pct"] and not cfg.get("resume_after_kill"):
        book["killed"] = True
    if cfg.get("resume_after_kill"):
        book["killed"] = False
    on = lambda v: v is not None
    return {"equity": round(eq, 2), "day_pct": round(day, 2), "week_pct": round(week, 2), "drawdown_pct": round(dd, 2),
            "no_new_today": on(b.get("day_loss_pct")) and day <= b["day_loss_pct"],
            "no_new_week": on(b.get("week_loss_pct")) and week <= b["week_loss_pct"],
            "risk_mult": 0.5 if on(b.get("halve_risk_drawdown_pct")) and dd <= b["halve_risk_drawdown_pct"] else 1.0,
            "killed": book["killed"]}
