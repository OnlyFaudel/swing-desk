"""Options radar scorebook: were options into earnings actually cheap or expensive?

Each radar reading (implied move from the at-the-money straddle vs what history says) is logged once per
earnings date. After the option expires we check how far the stock really moved and what the straddle would
have returned. Over time this tells the Options Specialist whether "looks cheap" means anything for our names.
"""
import json, os, datetime as dt

PATH = "memory/options_radar_log.json"


def _load():
    try:
        return json.load(open(PATH))
    except Exception:
        return {}


def _save(d):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    json.dump(d, open(PATH, "w"), indent=1)


def log(results, prices, today=None):
    today = str(today or dt.date.today())
    d = _load()
    for t, r in (results or {}).items():
        if not r or r.get("error") or not r.get("implied_move_pct"):
            continue
        k = f"{t}:{r['earnings']}"
        if k in d:
            continue
        d[k] = {"ticker": t, "earnings": r["earnings"], "expiry": r["expiry"], "logged": today, "price": round(float(prices.get(t) or 0), 2),
                "strike": r["strike"], "implied_move_pct": r["implied_move_pct"], "history_expected_move_pct": r["history_expected_move_pct"],
                "straddle_usd": r.get("straddle_cost_usd"), "looked_cheap": r.get("looks_cheap")}
    _save(d)
    return d


def resolve(today=None):
    """Fill in the real move for readings whose option has expired. Returns the newly resolved ones."""
    import yfinance as yf
    today = today or dt.date.today()
    d, done = _load(), []
    for k, r in d.items():
        if r.get("actual_move_pct") is not None or dt.date.fromisoformat(r["expiry"]) >= today:
            continue
        try:
            c = yf.download(r["ticker"], start=r["logged"], end=str(dt.date.fromisoformat(r["expiry"]) + dt.timedelta(days=4)),
                            auto_adjust=False, progress=False)["Close"]
            c = c.iloc[:, 0] if hasattr(c, "columns") else c
            c = c[c.index <= str(r["expiry"])]
            if c.empty:
                continue
            end = float(c.iloc[-1])
            ed = r["earnings"]
            pre = c[c.index < ed]
            post = c[c.index > ed]
            r["expiry_close"] = round(end, 2)
            r["actual_move_pct"] = round(abs(end / r["price"] - 1) * 100, 1)
            if len(pre) and len(post):  # covers both before-open and after-close reports
                r["earnings_jump_pct"] = round((float(post.iloc[0]) / float(pre.iloc[-1]) - 1) * 100, 1)
            prem = (r.get("straddle_usd") or 0) / 100
            if prem > 0:
                r["straddle_return_pct"] = round((abs(end - r["strike"]) - prem) / prem * 100)
            r["options_were"] = "cheap" if r["actual_move_pct"] > r["implied_move_pct"] else "expensive"
            done.append(r)
        except Exception as e:
            print("radar resolve", k, e)
    _save(d)
    return done


def summary():
    rs = [r for r in _load().values() if r.get("actual_move_pct") is not None]
    if not rs:
        return {"resolved": 0, "note": "No earnings options readings have expired yet."}
    cheap = [r for r in rs if r["options_were"] == "cheap"]
    sr = [r["straddle_return_pct"] for r in rs if r.get("straddle_return_pct") is not None]
    flagged = [r for r in rs if r.get("looked_cheap")]
    return {"resolved": len(rs), "options_were_cheap": f"{len(cheap)} of {len(rs)}",
            "avg_straddle_return_pct": round(sum(sr) / len(sr)) if sr else None,
            "when_radar_said_cheap": (f"{sum(1 for r in flagged if r['options_were'] == 'cheap')} of {len(flagged)} really were") if flagged else "no flags yet",
            "latest": [{k: r.get(k) for k in ("ticker", "earnings", "implied_move_pct", "actual_move_pct", "straddle_return_pct")} for r in rs[-5:]]}
