"""Judgment layer (owner, 2026-11-24): "we don't want set rules so the bot is just reading something and acting; the bot should
know the strategy, adapt, and learn from it, especially when it does bad."

How it works:
  * Every rule trade has a NOTE: what it is, why it works, the test result, when it fails, its live record, and the lessons
    from its own closed trades. All agents can read these notes.
  * Once a day, before the rule trades fire (15:10-15:37 ET), the Portfolio Manager reads the notes plus today's market and
    sets a STANCE per strategy (size x0 skip ... x1.5) and can single out stocks (e.g. skip a name with fresh bad news).
  * The rules still find the opportunities (that is where the tested edge is); the PM decides how hard to lean on them.
  * Every override is SCORED against what the plain rule would have done. If the PM's overrides lose money over 15+
    decisions, its room shrinks automatically (no skipping, no upsizing); if they make money, it gets the full range.
  * Big misses become lessons that go back into the notes.
"""
import datetime as dt

NOTES = {
    "panic_rebound": {"name": "Panic-day rebound",
              "what": "On a day the S&P falls 2%+, buy our stocks that fell 3%+ and sit 15%+ under their 20-day high; sell at +10% "
                      "at a close, a 5%+ morning gap (bought back near the close), or after 6 sessions.",
              "why": "Forced and fearful selling overshoots on market-wide panic days; nuclear names are high-beta so they overshoot most.",
              "fails": "When the panic is the start of a real bear market (2008, early 2020) and the next leg down comes within days.",
              "ledger": ["panic_rebound", "gap_bank_panic", "take_profit_early_panic"]},
    "sharp_drop": {"name": "Sharp-drop rebound",
                   "what": "Any day: a nuclear or related stock down 15%+ in 5 sessions gets 10% of the account (15% if down 20%+); "
                           "a second buy of the same dollars if it falls another 10%; sell at +10% or after 10 sessions.",
                   "why": "Fast drops are usually forced sellers and stop-loss cascades, not new information; they snap back.",
                   "fails": "When the drop IS new information: share offering, failed trial/licence, fraud, lost contract. Check the news.",
                   "ledger": ["sharp_drop", "sharp_drop_add"]},
    "comeback": {"name": "Intraday comeback",
                 "what": "With the S&P under its 200-day: a stock that dips 6%+ during the day and gets back above yesterday's close; "
                         "hold 20 sessions, -15% stop.",
                 "why": "Buyers absorbing a big intraday flush in a weak market is a sign of real demand.",
                 "fails": "Choppy markets where every bounce fails; it is restricted to below-200-day markets for that reason.",
                 "ledger": ["intraday_comeback"]},
    "ai_power": {"name": "AI power day",
                 "what": "NVIDIA up 6%+ in a day -> buy the power trio (CEG, VST, TLN), 15% split, 5 sessions.",
                 "why": "Big AI days re-rate the power-demand story; the power names follow with a lag.",
                 "fails": "When NVIDIA's jump is company-specific (one product) rather than AI demand overall.",
                 "ledger": ["ai_power", "cross_market"]},
    "fear_fade": {"name": "Fear fading",
                  "what": "VIX above 30 and falling 2 days in a row -> buy the lineup, 20%, 20 sessions, at most once in 28 days.",
                  "why": "When fear peaks and starts to ease, the most-sold stocks recover first.",
                  "fails": "A second fear spike (2008, 2022) after a short relief.",
                  "ledger": ["fear_fade", "cross_market"]},
    "thanksgiving": {"name": "Thanksgiving run-up",
                     "what": "Buy the lineup (15%) at Tuesday's close, sell at the Black Friday close.",
                     "why": "Holiday-week optimism and thin selling; a long-documented seasonal tendency.",
                     "fails": "Small edge, a coin-flip in any single year; never worth more than its small size.",
                     "ledger": ["holidays_quarters_earnings", "thanksgiving"]},
    "earnings_pop": {"name": "Earnings-pop drift",
                     "what": "A stock that jumped 8%+ on its earnings reaction day: buy 5% at the next close, hold 20 sessions (max 2 open).",
                     "why": "After a big earnings beat, investors and analysts adjust slowly, so the stock keeps drifting up (post-earnings drift).",
                     "fails": "When the jump is a short squeeze or the whole market ripped that day; small sample (41 past cases).",
                     "ledger": ["earnings_pop_drift"]},
    "ah_dip": {"name": "After-hours dip",
               "what": "One of our 10 trades 3%+ under its 4 PM close after hours on real volume: buy 8% with an after-hours limit, sell right after the next open (max 2).",
               "why": "After-hours trading is thin, so prices overshoot; by the next open only about half of the move is left.",
               "fails": "When the after-hours drop is real bad news (an offering, a failed license, fraud) that keeps falling into the open; worst 5% of past trades about -5%.",
               "ledger": ["after_hours_dip"]},
    "year_end": {"name": "Year-end bounce", "what": "December tax-loss losers bounce into January.",
                 "why": "Tax-loss selling pressure ends at year-end.", "fails": "Years when the losers keep losing (real bad news).",
                 "ledger": ["year_end"]},
    "uranium_momentum": {"name": "Uranium momentum", "what": "Spot uranium strength -> small buys in the miners.",
                         "why": "Miners re-price on the commodity with a lag.", "fails": "Spot moves on thin trading that reverses.",
                         "ledger": ["uranium_momentum"]},
}
JUDGED = set(NOTES)  # setups whose size the PM can adjust


def _ledger_text(keys):
    try:
        import json
        L = json.load(open("research/trial_ledger.json"))["strategies"]
    except Exception:
        return []
    return [f"{k}: {str(L[k].get('verdict'))[:400]}" for k in keys if k in L]


def live_record(st, setup):
    tr = [x for x in st["book"]["trades"] if x.get("setup") == setup]
    if not tr:
        return "no closed trades yet"
    w = sum(1 for x in tr if x.get("pnl", 0) > 0)
    return f"{len(tr)} closed, {w} winners, total ${sum(x.get('pnl', 0) for x in tr):+.2f}, avg {sum(x.get('ret', 0) for x in tr) / len(tr):+.2f}%"


def setup_lessons(st, setup, n=5):
    out = [f"{p['date']} {p['ticker']}: {p['lesson']}" for p in st.get("postmortems", [])
           if p.get("setup") == setup and p.get("lesson") and str(p["lesson"]).lower() != "none"]
    out += [x["lesson"] for x in (st.get("judgment") or {}).get("lessons", []) if x.get("setup") == setup]
    return out[-n:]


def scorecard(st, setup=None):
    J = st.get("judgment") or {}
    ds = [d for d in J.get("decisions", []) if d.get("resolved") and (setup is None or d["setup"] == setup) and d["mult"] != 1]
    val = sum(d.get("value", 0) for d in ds)
    return {"overrides_scored": len(ds), "value_usd": round(val, 2),
            "right": sum(1 for d in ds if d.get("value", 0) > 0), "wrong": sum(1 for d in ds if d.get("value", 0) < 0)}


def allowed_range(st, setup):
    """The PM's room adapts to its own record: overrides that lost money -> smaller room, that made money -> full room."""
    sc = scorecard(st, setup)
    if sc["overrides_scored"] >= 15 and sc["value_usd"] < 0:
        return 0.5, 1.0, "your overrides on this strategy lost money, so you may only trim (x0.5-x1), not skip or upsize"
    if sc["overrides_scored"] >= 15 and sc["value_usd"] > 0:
        return 0.0, 2.0, "your overrides on this strategy made money, so you have the full range x0-x2"
    return 0.0, 1.5, "standard range x0-x1.5 until 15 overrides are scored"


def notes_for_agents(st):
    out = {}
    for k, n in NOTES.items():
        lo, hi, why = allowed_range(st, k)
        out[k] = {**{x: n[x] for x in ("name", "what", "why", "fails")}, "test_results": _ledger_text(n["ledger"]),
                  "live_record": live_record(st, k), "lessons": setup_lessons(st, k), "your_judgment_record": scorecard(st, k),
                  "your_room": f"x{lo}-x{hi}: {why}"}
    return out


def daily(st, desk, today, context):
    """One PM call a day: stance per strategy + per-stock overrides, with reasons. Falls back to x1 (the plain rule)."""
    J = st.setdefault("judgment", {})
    if (J.get("stance") or {}).get("date") == str(today) or not (desk and desk.available):
        return J.get("stance")
    J["stance"] = {"date": str(today), "setups": {}, "tickers": {}, "summary": "agents unavailable: plain rules"}
    sys = ("Portfolio Manager, DAILY STANCE on our rule strategies before they trade at ~15:40 ET. The rules find the "
           "opportunities (that is where the tested edge is); you decide how hard to lean on each one TODAY. Read each strategy's "
           "note: what it is, why it works, its test results, when it fails, its live record, the lessons from its own trades, and "
           "your own override record. Then set size_mult per strategy inside 'your_room' (1.0 = the plain rule; 0 = skip today). "
           "Only move off 1.0 for a SPECIFIC reason you can name from today's facts (news on a stock, the market regime, a lesson "
           "that applies); 'feels risky' is not a reason. You may also set a per-stock multiplier for a named stock with fresh "
           "news. Every override is scored against the plain rule and your room shrinks if you lose money. "
           '{"setups":{"sharp_drop":{"size_mult":1.0,"reason":""}},"tickers":{"UUUU":{"size_mult":0.5,"reason":""}},'
           '"summary":"2 plain sentences for the owner"}')
    try:
        out = desk.ask("pm", "smart", sys, {"strategy_notes": notes_for_agents(st), "today": context}, max_tokens=1200)
    except Exception as e:
        print("judgment", e)
        return J["stance"]
    sets = {}
    for k, v in (out.get("setups") or {}).items():
        if k in JUDGED and isinstance(v, dict):
            lo, hi, _ = allowed_range(st, k)
            sets[k] = {"mult": max(lo, min(hi, float(v.get("size_mult", 1) or 0))), "reason": str(v.get("reason", ""))[:300]}
    tks = {}
    for t, v in (out.get("tickers") or {}).items():
        if isinstance(v, dict):
            tks[t.upper()] = {"mult": max(0.0, min(1.5, float(v.get("size_mult", 1) or 0))), "reason": str(v.get("reason", ""))[:300]}
    J["stance"] = {"date": str(today), "setups": sets, "tickers": tks, "summary": str(out.get("summary", ""))[:500]}
    return J["stance"]


def apply(st, setup, t, usd, price, today):
    """Called just before a rule buy. Returns (dollars, note). Records the decision so it can be scored later."""
    if setup not in JUDGED:
        return usd, ""
    S = (st.get("judgment") or {}).get("stance") or {}
    if S.get("date") != str(today):
        return usd, ""
    s, k = (S.get("setups") or {}).get(setup), (S.get("tickers") or {}).get(t)
    lo, hi, _ = allowed_range(st, setup)
    m = (s or {}).get("mult", 1.0) * (k or {}).get("mult", 1.0)
    m = max(lo if k is None else 0.0, min(hi, m))
    why = "; ".join(x["reason"] for x in (s, k) if x and x.get("reason") and x.get("mult", 1) != 1)
    if abs(m - 1) < 1e-9:
        return usd, ""
    d = st.setdefault("judgment", {}).setdefault("decisions", [])
    d.append({"date": str(today), "setup": setup, "t": t, "mult": round(m, 2), "rule_usd": round(usd, 2), "entry_px": price,
              "resolve_on": str(today + dt.timedelta(days={"comeback": 28, "fear_fade": 28, "sharp_drop": 14, "panic_rebound": 9}.get(setup, 7))),
              "reason": why, "resolved": False})
    del d[:-300]
    return usd * m, why


def resolve(st, prices, today):
    """Score overrides: value = (mult - 1) x rule dollars x the stock's move since the decision (approximate: ignores early exits)."""
    J = st.get("judgment") or {}
    out = []
    for d in J.get("decisions", []):
        if d.get("resolved") or d["resolve_on"] > str(today) or not prices.get(d["t"]):
            continue
        mv = prices[d["t"]] / d["entry_px"] - 1
        d.update({"resolved": True, "move_pct": round(mv * 100, 2), "value": round((d["mult"] - 1) * d["rule_usd"] * mv, 2)})
        out.append(d)
        if abs(d["value"]) >= 5:  # a meaningful miss or hit becomes a lesson in the strategy's note
            verdict = "right" if d["value"] > 0 else "WRONG"
            J.setdefault("lessons", []).append({"date": str(today), "setup": d["setup"], "lesson":
                f"{d['date']}: you set {d['t']} {NOTES[d['setup']]['name']} to x{d['mult']} because '{d['reason'][:120]}'; the stock "
                f"moved {d['move_pct']:+.1f}% after, so that override was {verdict} (${d['value']:+.2f} vs the plain rule)."})
            del J["lessons"][:-60]
    return out
