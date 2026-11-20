"""Swing Desk v7: PATIENT LEVELS. One simple rule, everything else is preparation around it.

THE RULE: put a buy order just above the nearest support level, leave it there up to 5 sessions, sell at the
next resistance, at the stop just under the support, or after 3 days. (2.8 years of hourly data: positive
in BOTH halves on 19 of 20 stocks; t > 3 out of sample. See research/.)

THE PREPARATION:
  weekly   rank a 20-stock watchlist by how the rule has worked on each lately; trade the top 4 + CCJ
  morning  intel brief, agents' read, options radar, re-place resting orders and stops
  all day  scan for new levels, keep the closest-to-filling setups armed, take profits, guards
  close    time exits, shadow setups
  evening  review, memory, post-mortems; Fridays: strategist, auditor, learning loop

  python run.py loop --minutes 13 | daemon | once [--force-morning --force-close --force-review --force-rank]
  python run.py test-notify | test-agents | test-broker
"""
import json, os, sys, time, traceback, datetime as dt
import urllib.request

import gate, signals, feed, shadow, options_rec, inbox, market, news, intel, account, learning, ops, memory, patient, broker as brk, dashboard
from agents import Desk, Budget, MOCK

ROOT = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(ROOT, "config.json")))
STATE_PATH = os.path.join(ROOT, "state.json")
T = []          # this week's lineup (set every cycle from state["active"])
BROKER, DESK = {}, {}


# ======================================================================= plumbing
def ntfy_topic():
    """Accepts the bare name or a pasted link like https://ntfy.sh/name; strips spaces."""
    t = (os.environ.get("NTFY_TOPIC") or "").strip()
    for pre in ("https://", "http://", "ntfy.sh/"):
        if t.startswith(pre):
            t = t[len(pre):]
    return t.strip("/ ") or None


NOTIFY_ERR = []


def notify(title, body, tags="chart_with_upwards_trend", priority="default", who=None):
    topic = ntfy_topic()
    print(f"[notify] {title} | {body}")
    w = who or feed.who_for_title(title)
    feed.post(w, body, [t for t in T if t in f"{title} {body}"], kind="alert", title=title)
    feed.say(w, f"{title}. {body}", outcome=True)
    if not topic or MOCK:
        return
    try:
        req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode(),
                                     headers={"Title": title.encode("ascii", "ignore").decode(), "Tags": tags, "Priority": priority})
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print("notify failed", e)
        NOTIFY_ERR.append(str(e))


def notify_once(st, key, title, body):
    k = f"{key}:{dt.date.today()}"
    if not st["flags"].get(k):
        st["flags"][k] = True
        notify(title, body, tags="warning")


def load_state():
    if os.path.exists(STATE_PATH):
        return json.load(open(STATE_PATH))
    return {"created": str(dt.date.today()), "book": account.new_book(CFG["capital_cap"]), "flags": {},
            "benchmark": {"shares": None, "equity": []}, "pending_meta": {}, "armed": {}, "candidates": {},
            "setup_log": [], "cooldown": {}, "news_feed": [], "reviews": [], "audits": [], "brief": {}, "morning": {},
            "orders_log": [], "active": list(CFG["always_include"]), "ranking": {}}


def save_state(st):
    feed.flush(st)
    tmp = STATE_PATH + ".tmp"
    json.dump(st, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, STATE_PATH)


def log_order(st, o, note):
    st["orders_log"].append({"time": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "symbol": o.get("symbol"),
                             "side": o.get("side"), "kind": o.get("kind"), "qty": o.get("qty"), "price": o.get("price"),
                             "status": o.get("status"), "note": note})
    del st["orders_log"][:-300]


def tcfg(st):
    return news.ticker_cfg(CFG, T, st.setdefault("cache", {}))


def traded(st):
    """Tickers the bot must manage: this week's lineup plus anything still held or armed."""
    held = [t for t, l in st["book"]["lots"].items() if l.get("trade", {}).get("qty", 0) > 1e-6]
    return list(dict.fromkeys(T + held + list(st["armed"])))


# ======================================================================= execution trader (code)
class Exec:
    def __init__(self, st, br):
        self.st, self.br = st, br

    def buy_limit(self, t, qty, limit, tag, meta, note):
        try:
            o = self.br.limit_buy(t, qty, limit, tag)
        except Exception as e:
            ops.note_reject(self.st, CFG, notify, f"{t} {tag}: {e}")
            return None
        ops.note_order(self.st, CFG, notify)
        self.st["pending_meta"][o["client_id"]] = meta
        log_order(self.st, o, note)
        return o

    def place_stop(self, t, stop):
        L = account.lot(self.st["book"], t, "trade")
        if L["qty"] <= 1e-6:
            return
        for _ in (1, 2):
            try:
                o = self.br.stop_sell(t, L["qty"], stop, "stop")
                L["stop_order"] = o["id"]
                log_order(self.st, o, f"protective stop ${stop:.2f}")
                ops.note_order(self.st, CFG, notify)
                return
            except Exception as e:
                ops.note_reject(self.st, CFG, notify, f"{t} stop: {e}")
                time.sleep(0 if self.br.name == "sim" else 2)
        notify(f"STOP FAILED {t}: exiting", f"Could not place a stop at ${stop:.2f} twice, so the trade is being closed.",
               tags="rotating_light", priority="high")
        px = market.INTRADAY[t].Close.iloc[-1] if market.INTRADAY.get(t) is not None else L["stop"]
        self.exit_trade(t, px, "no stop could be placed")

    def exit_trade(self, t, price, reason, tag="exit"):
        L = account.lot(self.st["book"], t, "trade")
        if L["qty"] <= 1e-6:
            return
        if L.get("stop_order"):
            self.br.cancel(L["stop_order"])
            time.sleep(0 if self.br.name == "sim" else 1.5)
        L["exit_reason"] = reason
        try:
            o = self.br.market_sell(t, L["qty"], price, tag)
            log_order(self.st, o, reason)
        except Exception as e:
            notify(f"EXIT FAILED {t}", f"{reason}: {str(e)[:150]}", tags="rotating_light", priority="high")


# ======================================================================= fills + learning
def process_fills(st, br, ex, today):
    fills = br.sync(market.INTRADAY) if br.name == "sim" else br.sync()
    book = st["book"]
    for f in fills:
        meta = st["pending_meta"].pop(f.get("client_id"), None)
        tag = account.tag_of(f.get("client_id"))
        rec = account.apply_fill(book, f, today, meta)
        if tag == "pl" and f["side"] == "buy":
            st["armed"].pop(f["symbol"], None)
            st["candidates"].pop(f["symbol"], None)
            L = account.lot(book, f["symbol"], "trade")
            ex.place_stop(f["symbol"], L["stop"])
            if CFG["notify"]["trades"]:
                notify(f"BOUGHT {f['symbol']} at support",
                       f"{f['qty']:.4f} sh @ ${f['fill_price']:.2f} = ${f['qty'] * f['fill_price']:.2f} | stop ${L['stop']:.2f} | "
                       f"target ${L['target']:.2f} | {L.get('why', '')[:90]}", tags="large_blue_circle")
        elif tag.startswith("core") and CFG["notify"]["trades"]:
            notify(f"CORE {f['side'].upper()} {f['symbol']}", f"{f['qty']:.4f} sh @ ${f['fill_price']:.2f}", tags="moneybag")
        if rec:
            if CFG["notify"]["trades"]:
                notify(f"SOLD {rec['ticker']} {'+' if rec['pnl'] >= 0 else ''}{rec['ret']:.1f}%",
                       f"P&L {'+' if rec['pnl'] >= 0 else '-'}${abs(rec['pnl']):.2f} | {rec['why_out']}",
                       tags="green_circle" if rec["pnl"] >= 0 else "red_circle")
            postmortem(st, rec)


def postmortem(st, rec):
    desk = DESK.get("d")
    if not (desk and desk.available and CFG["learning"]["postmortems"]):
        return
    try:
        with feed.thread(f"Postmortem {rec['ticker']}: {rec.get('pnl', 0):+.2f} on the trade", [rec["ticker"]], kind="postmortem"):
            feed.say("exec", f"Closing note on {rec['ticker']}: bought ${rec.get('entry', rec.get('entry_price', 0))}, "
                     f"sold ${rec.get('exit', rec.get('exit_price', 0))}, result ${rec.get('pnl', 0):+.2f}. Why did it go this way?")
            pm = desk.postmortem({"trade": rec, "headlines_during_trade": [f["title"] for f in st["news_feed"] if f["ticker"] == rec["ticker"]][-8:],
                              "market_brief": (st.get("morning") or {}).get("macro"), "memory_playbook": memory.playbook(st, rec["ticker"])})
    except Exception as e:
        print("postmortem failed", e)
        return
    entry = {"date": str(dt.date.today()), "ticker": rec["ticker"], "setup": rec["setup"], "pnl": rec["pnl"], "ret": rec["ret"],
             **{k: pm.get(k) for k in ("verdict", "decision_quality", "what_happened", "lesson")}}
    st.setdefault("postmortems", []).append(entry)
    del st["postmortems"][:-150]
    if CFG["notify"].get("postmortems") and rec["pnl"] < 0:
        notify(f"Why {rec['ticker']} lost: {pm.get('verdict', '?')}", f"{pm.get('what_happened', '')[:180]} Lesson: {pm.get('lesson', 'none')}", tags="mag")


def lessons(st, n=8):
    return [f"{p['ticker']} ({p['verdict']}): {p['lesson']}" for p in st.get("postmortems", [])
            if p.get("lesson") and str(p["lesson"]).lower() != "none"][-n:]


def active_theses(st, t=None):
    out = [th for th in st.get("theses", []) if th.get("status") == "open" and (not t or t in th.get("tickers", []))]
    return [{k: th.get(k) for k in ("tickers", "thesis", "catalyst", "catalyst_date", "direction", "kills", "conviction", "created")} for th in out][-6:]


# ======================================================================= weekly lineup (self-selection)
def weekly_rank(st, force=False):
    wk = "%d-W%02d" % dt.date.today().isocalendar()[:2]
    if st.get("ranking", {}).get("week") == wk and not force:
        return
    import yfinance as yf
    hourly = {}
    for t in CFG["watchlist"]:
        try:
            h = yf.download(t, period="729d", interval="1h", auto_adjust=True, progress=False)
            h.columns = h.columns.get_level_values(0)
            h = h.dropna()
            h.index = h.index.tz_convert("America/New_York")
            hourly[t] = h
        except Exception as e:
            print("rank fetch failed", t, e)
    r = patient.rank_universe(hourly, weeks=CFG["rank_weeks"])
    try:
        dashboard.write_lab(hourly)
    except Exception as e:
        print("lab data failed", e)
    picks = [t for t in r if t not in CFG["always_include"]][:CFG["picks_n"]]
    old = st.get("active", [])
    if CFG.get("lineup_mode") == "fixed":   # the synchronized trio: same three stocks every week
        st["active"] = list(CFG["tickers"])
        st["ranking"] = {"week": wk, "date": str(dt.date.today()), "scores": r, "active": st["active"], "mode": "fixed"}
        if old != st["active"]:
            notify("Lineup", f"The nuclear fuel chain, 3 trades at a time: {', '.join(st['active'])}. "
                   "Practice trades keep running on 52 stocks.", tags="trophy")
        return
    st["active"] = list(CFG["always_include"]) + picks
    st["ranking"] = {"week": wk, "date": str(dt.date.today()), "scores": r, "active": st["active"]}
    notify("This week's lineup", f"{', '.join(st['active'])} (was {', '.join(old) or 'none'}). Top by how Patient Levels "
           f"worked on each over the last {CFG['rank_weeks']} weeks: " +
           ", ".join(f"{t} {v['score']:+.2f}%" for t, v in list(r.items())[:5]), tags="trophy")


# ======================================================================= candidates + arming (the one strategy)
def sessions_after(d0, n):
    import numpy as np
    return str(np.busday_offset(d0, n, roll="forward"))


def refresh_candidates(st, desk, data, prices, today, brk_state, force=False):
    """Find a support setup for each lineup stock without a trade; keep it (fixed zone) for up to 5 sessions."""
    P = CFG["patient"]
    now = market.now_et()
    if now.time() > dt.time(*map(int, P["last_entry_time"].split(":"))) and not force:
        return
    book = st["book"]
    hourly = market.fetch_hourly(T)
    for t, c in list(st["candidates"].items()):
        if str(today) > c["valid_until"] or t not in T:
            st["candidates"].pop(t)
            if t in st["armed"]:
                ex_cancel(st, t)
    scans = st.setdefault("last_scan", {})
    for t in T:
        if account.lot(book, t, "trade")["qty"] > 1e-6 or t in st["candidates"]:
            continue
        if time.time() - scans.get(t, 0) < P["scan_minutes"] * 60 and not force:
            continue
        scans[t] = time.time()
        d = market.trading_days_until(market.next_earnings(t))
        why = st.setdefault("setup_status", {})
        if d is not None and 0 <= d <= CFG["no_entry_days_before_earnings"]:
            why[t] = f"earnings in {d} trading day(s), so no new trades until after"
            continue
        if skew_veto(st, t):
            why[t] = "options traders are paying up for crash protection (skew veto), so it sits out"
            continue
        h = hourly.get(t)
        if h is not None and len(h) and h.index[-1].date() == today and now.time() < dt.time(15, 59):
            h = h.iloc[:-1]  # use completed hourly bars only
        s = patient.setup_now(h, {"front": P["front_run_pct"], "pad": P["stop_below_zone_pct"], "rr": P["min_reward_risk"]})
        if not s:
            why[t] = patient.why_no_setup(h)
            continue
        why[t] = "setup found"
        decision, reason = "ARM", "rules (agents off)"
        if desk.available:
            try:
                lv = desk.level_trader({t: s}, {"strategy": "Patient Levels: order rests up to 5 sessions, max hold 3 days",
                                                "morning_intel": {k: (st.get("morning") or {}).get(k) for k in ("whale", "crowd", "macro")},
                                                "chart": market.snapshot(data[t], prices[t]), "lessons_from_past_trades": lessons(st),
                                                "desk_memory_playbook": memory.playbook(st, t), "active_theses": active_theses(st, t),
                                                "recent_headlines": [f["title"] for f in st["news_feed"] if f["ticker"] == t][-8:]})
                v = (lv.get("setups") or {}).get(t, {})
                decision, reason = str(v.get("decision", "ARM")).upper(), v.get("reason", "")
            except Exception as e:
                print("level trader failed", e)
        st["setup_log"].append({"date": str(today), "ticker": t, **s, "decision": decision, "reason": reason[:200], "evaluated": False})
        del st["setup_log"][:-500]
        if decision != "ARM":
            why[t] = f"the Level Analyst skipped the setup: {reason}"[:200]
        if decision == "ARM":
            st["candidates"][t] = {**s, "created": str(today), "valid_until": sessions_after(str(today), P["valid_sessions"] - 1),
                                   "reason": reason}


def sync_state(st, hourly):
    """One shared pulse for the trio + each stock's partners. Research (train year 1, test year 2, two trios):
    level trades did better when the trio basket was above its 10-day average (4 of 4 tests) and when a stock
    dipped while its partners rose; sizing tilts toward those, never to zero (the bot keeps trading)."""
    c = CFG["sync"]
    tk = [t for t in T if t in hourly and len(hourly[t]) > c["pulse_hours"] + 2]
    if not c["enabled"] or len(tk) < 2:
        return {"mult": {t: 1.0 for t in T}}
    import pandas as pd
    C = pd.DataFrame({t: hourly[t].Close for t in tk}).ffill().dropna()
    basket = (C / C.iloc[0]).mean(axis=1)
    avg = basket.rolling(c["pulse_hours"]).mean()
    pulse_up = bool(basket.iloc[-1] > avg.iloc[-1])
    r = C.pct_change(c["partner_hours"]).iloc[-1]
    out = {"pulse_up": pulse_up, "basket_vs_avg_pct": round(float((basket.iloc[-1] / avg.iloc[-1] - 1) * 100), 2),
           "partners_pct": {}, "mult": {}, "own_pct": {t: round(float(r[t] * 100), 2) for t in tk}}
    for t in tk:
        peers = float(r[[p for p in tk if p != t]].mean() * 100)
        m = c["pulse_up_mult"] if pulse_up else c["pulse_down_mult"]
        m *= c["partners_up_mult"] if peers > 0 else c["partners_selloff_mult"] if peers < c["partners_selloff_pct"] else 1.0
        out["partners_pct"][t] = round(peers, 2)
        out["mult"][t] = round(max(c["min_mult"], min(c["max_mult"], m)), 2)
    tail = C.iloc[-140:]
    out["series"] = {t: [round(float(v), 4) for v in (tail[t] / tail[t].iloc[0])] for t in tk}
    out["series"]["basket"] = [round(float(v), 4) for v in (basket.iloc[-140:] / basket.iloc[-140])]
    out["series"]["avg"] = [round(float(v), 4) if v == v else None for v in (avg.iloc[-140:] / basket.iloc[-140])]
    out["time"] = market.now_et().strftime("%Y-%m-%d %H:%M")
    return out


def ex_cancel(st, t):
    a = st["armed"].pop(t, None)
    if a:
        BROKER["b"].cancel(a["order_id"])


def arm(st, ex, prices, today, brk_state):
    """Keep resting buy orders on the candidates most likely to fill, as many as free slots and settled cash allow."""
    book = st["book"]
    if brk_state["killed"] or brk_state.get("ops_halt") or brk_state["no_new_today"] or brk_state["no_new_week"]:
        for t in list(st["armed"]):
            ex_cancel(st, t)
        return
    open_trades = [t for t in traded(st) if account.lot(book, t, "trade")["qty"] > 1e-6]
    free = CFG["slots"] - len(open_trades)
    eq = brk_state["equity"]
    slot_usd = min(eq / CFG["slots"], eq * CFG["max_position_pct"] / 100) * learning.mult(st, "patient_level") * brk_state["risk_mult"]
    try:
        st["sync"] = sync_state(st, market.fetch_hourly(T))
    except Exception as e:
        st["sync"] = {"mult": {}, "error": str(e)[:120]}
    if CFG["sync"].get("pulse_filter") and st["sync"].get("pulse_up") is False:
        for t in list(st["armed"]):
            ex_cancel(st, t)
        if not st["flags"].get(f"pulsehold:{today}"):
            st["flags"][f"pulsehold:{today}"] = True
            b_ = st["sync"].get("basket_vs_avg_pct")
            feed.post("risk", f"The whole nuclear basket is falling ({b_:+.1f}% vs its 10-day average), so no new buys until it turns up. "
                      "Open trades and their stops are unchanged. Research: this cut the worst drops roughly in half, at the cost of fewer trades.",
                      kind="alert", art={"big": "Sector falling: holding off", "sub": "No new buys until the basket turns up"})
            feed.say("risk", "Pausing new buys: the basket is below its 10-day average.", to="team")
        return
    cands = sorted(((c, t) for t, c in st["candidates"].items() if t in prices),
                   key=lambda x: prices[x[1]] / x[0]["entry"] - 1)  # closest to filling first
    # a price already at/below the stop means the level broke: a fill there is an instant stop-out, so don't rest it
    cands = [(c, t) for c, t in cands if prices[t] > c["stop"]]
    want = [t for c, t in cands][:max(free, 0)]
    for t in list(st["armed"]):
        if t not in want:
            ex_cancel(st, t)
    cash = account.settled_cash(book, today) - sum(a["dollars"] for a in st["armed"].values())
    for c, t in cands:
        if t not in want or t in st["armed"]:
            continue
        sm = st["sync"].get("mult", {}).get(t, 1.0)
        dollars = min(slot_usd * sm, eq * CFG["max_position_pct"] / 100, cash)
        if dollars < CFG["min_trade_usd"]:
            continue
        qty = dollars / c["entry"]
        o = ex.buy_limit(t, qty, c["entry"], "pl",
                         {"setup": "patient_level", "stop": c["stop"], "target": c["target"], "zone": c["zone"],
                          "max_days": c["max_days"], "by": "agents" if DESK["d"].available else "rules",
                          "why": f"support ${c['zone']} (R:R {c['reward_risk']}). {c.get('reason', '')}"[:200]},
                         f"Patient Levels buy above ${c['zone']}")
        if o:
            cash -= dollars
            st["armed"][t] = {**c, "qty": round(qty, 6), "dollars": round(dollars, 2), "order_id": o["id"]}
            if CFG["notify"]["orders_armed"] and not st["flags"].get(f"armednote:{t}:{c['created']}"):
                st["flags"][f"armednote:{t}:{c['created']}"] = True
                notify(f"ARMED {t}: buy ${c['entry']:.2f}",
                       f"${dollars:.0f} resting above support ${c['zone']:.2f} (now ${prices[t]:.2f}, {c['dist_to_entry_pct']:+.1f}% away). "
                       f"Stop ${c['stop']:.2f}, target ${c['target']:.2f}, {c['reward_risk']}x. Valid to {c['valid_until']}. "
                       f"Trio sync size {sm:.2f}x ({'pulse up' if st['sync'].get('pulse_up') else 'pulse down'}).", tags="dart")


# ======================================================================= intel helpers
def skew_veto(st, t):
    c = CFG["skew_veto"]
    hist = [d[t]["skew"] for d in st.get("intel_history", {}).values() if t in d and d[t].get("skew") is not None]
    if not c["enabled"] or len(hist) < c["min_history"]:
        return False
    rank = sum(1 for x in hist if x <= hist[-1]) / len(hist) * 100
    return rank >= c["percentile"]


def record_intel(st, b, today):
    h = st.setdefault("intel_history", {})
    row = {}
    for t, x in (b.get("tickers") or {}).items():
        o = x.get("options") or {}
        row[t] = {"skew": o.get("put_skew_pts"), "gex": o.get("net_dealer_gamma_musd_per_1pct"), "iv": o.get("atm_iv_pct"),
                  "pc_oi": o.get("put_call_oi"), "short_z": (x.get("short_volume") or {}).get("zscore"),
                  "reddit": (x.get("reddit") or {}).get("mentions_24h")}
    h[str(today)] = row
    for k in sorted(h)[:-400]:
        del h[k]


def run_radar(st, prices, earnings):
    if not CFG["options_radar"]["enabled"]:
        return
    memory.bootstrap_earnings(T)
    res = {}
    for t in T:
        try:
            r = memory.options_radar(t, prices[t], earnings.get(t), CFG)
        except Exception as e:
            r = {"error": str(e)[:120]}
        if r:
            res[t] = r
            key = f"radar:{t}:{r.get('earnings')}"
            if r.get("looks_cheap") and r.get("affordable") and not st["flags"].get(key):
                st["flags"][key] = True
                notify(f"OPTIONS RADAR {t}: options look cheap into earnings",
                       f"Options imply ±{r['implied_move_pct']}% by {r['expiry']}; {t}'s history says ±{r['history_expected_move_pct']}%. "
                       f"Capped-loss call spread {r['call_spread']} ${r['call_spread_cost_usd']}. Alert only; max loss = what you pay.",
                       tags="crystal_ball", priority="high")
    st["radar"] = {"date": str(dt.date.today()), "results": res}


# ======================================================================= morning
def morning(st, desk, br, ex, data, prices, today, brk_state):
    book = st["book"]
    if br.name == "sim":
        br.expire_day_orders()
    st["pending_meta"], st["armed"] = {}, {}
    for t in traded(st):  # re-place DAY stops
        L = account.lot(book, t, "trade")
        if L["qty"] > 1e-6 and L.get("stop"):
            ex.place_stop(t, L["stop"])
    with feed.thread(f"Morning meeting {today:%a %b %d}", T, kind="morning"):
        held_now = [t for t in traded(st) if account.lot(book, t, "trade")["qty"] > 1e-6]
        feed.say("chief", f"Morning, team. Lineup {', '.join(T)}. Account ${brk_state['equity']:,.2f}, "
                 f"{brk_state['week_pct']:+.2f}% this week. Open trades: {', '.join(held_now) or 'none'}. "
                 "Nowcast first, then macro, whales and the crowd; the Level Analyst decides which buys to rest.")
        nc_line = ""
        try:  # Asia's close -> expected opening gap (information only; research/ccj_leadlag.py)
            st["nowcast"] = signals.nowcast(T)
            g = [f"{t} {v['expected_gap_pct']:+.1f}%" for t, v in st["nowcast"].items() if v.get("expected_gap_pct") is not None]
            nc_line = (" | Asia says open: " + ", ".join(g)) if g else ""
            feed.say("nowcast", ("Asia's close points to these opens: " + ", ".join(g) + ". That's already priced in at 9:30, so treat it as context, not a trade.") if g else "No fresh Asia close yet.")
            feed.post("nowcast", ("Asia's close points to these opens: " + ", ".join(g) + ". Information only: the open prices this in, "
                      "so it never places a trade.") if g else "No fresh Asia close yet.", T, kind="data",
                      art={"big": "Asia says: " + ", ".join(g), "sub": "Expected opening moves. Background only."} if g else None)
        except Exception as e:
            st["nowcast"] = {"error": str(e)[:120]}
        earnings = {t: market.next_earnings(t) for t in T}
        b = intel.morning_brief(tcfg(st), st.setdefault("cache", {}), prices, earnings)
        st["brief"] = b
        record_intel(st, b, today)
        run_radar(st, prices, earnings)
        for t in traded(st):  # don't hold a trade through earnings
            d = market.trading_days_until(market.next_earnings(t))
            if d is not None and 0 <= d <= CFG["exit_trading_before_earnings_days"] and account.lot(book, t, "trade")["qty"] > 1e-6:
                ex.exit_trade(t, prices[t], f"earnings {market.next_earnings(t)}: not holding a trade through it")
        mo = {"date": str(today)}
        if desk.available:
            try:
                mo["macro"] = desk.macro(b.get("market"), b.get("calendar"))
                mo["whale"] = desk.whale_watcher({t: {k: b["tickers"][t].get(k) for k in ("price", "options", "short_volume", "insiders", "fundamentals")} for t in T})
                twits = {}
                if CFG.get("news_sources", {}).get("stocktwits"):
                    for t in T:
                        try:
                            twits[t] = news.stocktwits(t)
                        except Exception:
                            pass
                st["stocktwits"] = twits
                mo["crowd"] = desk.crowd({t: {"reddit": b["tickers"][t].get("reddit"), "stocktwits": twits.get(t),
                                              "analysts": b["tickers"][t].get("fundamentals")} for t in T})
            except Exception as e:
                mo["agent_error"] = str(e)[:200]
                notify_once(st, "agent_error", "Agent desk error", f"{e}"[:200] + " Rules keep running.")
        st["morning"] = mo
        refresh_candidates(st, desk, data, prices, today, brk_state, force=True)
        arm(st, ex, prices, today, brk_state)
        try:
            st["gap_flags"] = signals.gap_risk(st.get("nowcast") or {}, st["armed"])
            for t, why in st["gap_flags"].items():
                notify_once(st, f"gapflag:{t}:{today}", f"Open watch {t}", why, tags="eyes")
        except Exception as e:
            print("gap flags failed", e)
        if CFG["notify"]["morning_brief"]:
            m = mo.get("macro") or {}
            notify("Morning brief", f"Lineup {', '.join(T)} | risk {m.get('risk_level', 'n/a')} | armed: "
                   + (", ".join(f"{t} ${a['entry']}" for t, a in st["armed"].items()) or "none")
                   + f" | waiting: {', '.join(t for t in st['candidates'] if t not in st['armed']) or 'none'}" + nc_line, tags="sunrise")


# ======================================================================= hawk mode (always-on VM)
HAWK_EVENTS = []


def hawk_stream(st, wake):
    """Live trades from Alpaca's free IEX feed. Wakes the bot at once when a held trade touches its target or stop,
    or when a stock moves fast (a likely news reaction), instead of waiting for the next minute."""
    import collections
    hk = CFG["hawk"]
    hist = collections.defaultdict(collections.deque)
    last_wake = [0.0]
    try:
        from alpaca.data.live import StockDataStream
        from alpaca.data.enums import DataFeed
        ds = StockDataStream(os.environ["ALPACA_KEY"], os.environ["ALPACA_SECRET"], feed=DataFeed.IEX)

        async def on_trade(tr):
            t, px, now = tr.symbol, float(tr.price), time.time()
            market.LIVE[t] = (px, now)
            q = hist[t]; q.append((now, px))
            while q and now - q[0][0] > hk["move_window_min"] * 60:
                q.popleft()
            why = None
            L = account.lot(st["book"], t, "trade")
            if L.get("qty", 0) > 1e-6 and L.get("target") and px >= L["target"]:
                why = f"{t} touched its target ${L['target']:.2f}"
            elif q and abs(px / q[0][1] - 1) * 100 >= hk["move_alert_pct"] and now - q[0][0] > 60:
                why = f"{t} moved {(px / q[0][1] - 1) * 100:+.1f}% in {int((now - q[0][0]) / 60)} min"
                q.clear()
            if why and now - last_wake[0] > 15:
                last_wake[0] = now
                HAWK_EVENTS.append(why)
                wake.set()
        ds.subscribe_trades(on_trade, *T)
        ds.run()
    except Exception as e:
        print("price stream stopped", e)


def hawk_events(st):
    """Called each cycle: a fast move makes the whole news net (slow lane too) run right now."""
    if not HAWK_EVENTS:
        return
    ev = list(dict.fromkeys(HAWK_EVENTS)); HAWK_EVENTS.clear()
    st["news_slow_at"] = 0
    feed.post("chief", "Hawk alert: " + "; ".join(ev) + ". Checking every news channel for a reason right now.",
              [t for t in T if any(e.startswith(t) for e in ev)], kind="alert",
              art={"big": ev[0], "sub": "Live price alert. The team is checking the news."})


# ======================================================================= owner posts (the owner asks the team to look now)
def handle_owner_posts(st, desk, ex, data, prices, today, brk_state):
    cfg = CFG.get("owner_posts", {})
    if not cfg.get("enabled"):
        return
    try:
        msgs = inbox.poll()
    except Exception as e:
        print("inbox poll failed", e); return
    seen = st.setdefault("inbox_seen", [])
    done_today = sum(1 for x in st.get("owner_posts", []) if x["date"] == str(today))
    for m in sorted(msgs, key=lambda x: x["time"]):
        if m["id"] in seen:
            continue
        seen.append(m["id"]); del seen[:-300]
        if done_today >= cfg.get("max_per_day", 8):
            feed.post("chief", f"Got your post, but that's {done_today} today, the daily cap. We'll pick it up tomorrow if it still matters.")
            continue
        done_today += 1
        st.setdefault("owner_posts", []).append({"date": str(today), "id": m["id"], "text": m["text"]})
        del st["owner_posts"][:-100]
        owner_scan(st, desk, ex, data, prices, today, brk_state, m["text"])


def owner_scan(st, desk, ex, data, prices, today, brk_state, text):
    import re
    words = set(re.findall(r"[A-Z]{2,5}", text.upper()))
    extra = sorted(w for w in words if w in shadow.GROUP and w not in T)[:3]
    feed.post("owner", text, [t for t in T if t in words] + extra, kind="owner")
    with feed.thread(f"You asked: {text[:70]}", list(T) + extra, kind="owner"):
        feed.say("owner", text, to="team")
        feed.say("chief", "On it. Re-scanning all three stocks for a support setup right now, ignoring the usual 30-minute wait."
                 + (f" I'll also check {', '.join(extra)} for you, for information only, since they're not in our trio." if extra else ""), to="owner")
        st.setdefault("last_scan", {}).clear()
        before = set(st["candidates"])
        refresh_candidates(st, desk, data, prices, today, brk_state, force=True)
        is_open = market.market_open()
        if is_open:
            arm(st, ex, prices, today, brk_state)
        found = {t: st["candidates"][t] for t in T if t in st["candidates"]}
        why = {t: (st.get("setup_status") or {}).get(t) for t in T if t not in found}
        info = {}
        if extra:
            try:
                hx = market.fetch_hourly(extra)
                for t in extra:
                    s_ = patient.setup_now(hx.get(t))
                    info[t] = s_ or {"none": patient.why_no_setup(hx.get(t))}
            except Exception as e:
                info = {"error": str(e)[:100]}
        lines = [f"{t}: buy zone ${c['entry']} (support ${c['zone']}), stop ${c['stop']}, target ${c['target']}" for t, c in found.items()]
        lines += [f"{t}: nothing yet, {w}" for t, w in why.items() if w]
        lines += [f"{t} (info only): " + (f"support setup at ${v['entry']}" if "entry" in v else v.get("none", "?")) for t, v in info.items() if isinstance(v, dict)]
        feed.say("level", "Scan results:\n" + "\n".join(lines), to="owner")
        new = set(found) - before
        if new and is_open:
            feed.say("exec", "Placed: " + ", ".join(f"{t} buy at ${st['armed'][t]['entry']}" for t in new if t in st["armed"]), to="owner", outcome=True)
        elif new:
            feed.say("exec", "The market is closed, so these buys go in at the next open: " + ", ".join(new), to="owner", outcome=True)
        ans = None
        if desk.available:
            try:
                ans = desk.answer_owner({"owner_post": text, "setups_found": found, "why_no_setup": why, "info_only": info,
                                         "market_open": is_open, "nowcast": st.get("nowcast"), "prices": {t: prices.get(t) for t in T}})
            except Exception as e:
                print("owner answer failed", e)
        headline = (ans or {}).get("post") or (f"Found {len(found)} setup{'s' if len(found) != 1 else ''}" if found else "Nothing safe to buy yet")
        feed.post("pm", (ans or {}).get("say") or "\n".join(lines), list(found) or T, kind="answer",
                  art={"big": headline[:60], "sub": "Answer to your post"})
    notify("Team answered your post", headline, tags="speech_balloon", who="pm")


# ======================================================================= news (agents: veto + exits)
def handle_news(st, desk, ex, data, prices, today, brk_state):
    fresh = news.new_items(tcfg(st), st)
    if not fresh:
        return
    scored = {}
    if desk.available:
        try:
            for s in desk.scout(fresh[:40]):
                scored[s.get("id")] = s
        except Budget:
            pass
        except Exception as e:
            notify_once(st, "agent_error", "Agent desk error", f"{e}"[:200] + " Rules keep running.")
    feed = st["news_feed"]
    for it in fresh:
        s = scored.get(it["id"], {})
        feed.append({**{k: it[k] for k in ("ticker", "source", "title", "link", "ts")},
                     **{k: s.get(k) for k in ("materiality", "novelty", "direction", "event_type", "why")}})
        if (s.get("materiality") or 0) >= 6 and it["ticker"] in prices:
            memory.remember(st, {**it, **s}, prices[it["ticker"]])
    del feed[:-250]
    groups = {}
    for it in fresh:
        s = scored.get(it["id"], {})
        if (s.get("materiality") or 0) >= CFG["materiality_to_convene_desk"] and s.get("novelty") != "stale":
            groups.setdefault(it["ticker"], []).append({**it, **s})
    for t, mat in groups.items():
        top = max(m["materiality"] for m in mat)
        if time.time() - st["cooldown"].get(t, 0) < CFG["desk_cooldown_minutes"] * 60 and top < 9:
            continue
        st["cooldown"][t] = time.time()
        if CFG["notify"]["material_news"]:
            notify(f"News {t} ({top}/10)", mat[0]["title"][:200] + " - desk reviewing", tags="newspaper")
        convene_news(st, desk, ex, data, prices, today, t, mat)


def convene_news(st, desk, ex, data, prices, today, t, mat):
    with feed.thread(f"News on {t}: {mat[0]['title'][:70]}", [t], kind="news"):
        _convene_news(st, desk, ex, data, prices, today, t, mat)


def _convene_news(st, desk, ex, data, prices, today, t, mat):
    book = st["book"]
    held = account.lot(book, t, "trade")["qty"] > 1e-6
    entry = {"ticker": t, "trigger": "news", "headline": mat[0]["title"][:160]}
    feed.say("scout", f"Flagging this for the team: \"{mat[0]['title'][:140]}\" ({mat[0].get('source', '')}). "
             f"{'We hold a trade in ' + t + '.' if held else ('We have a buy waiting on ' + t + '.' if t in st['candidates'] else 'No position in ' + t + '.')}")
    try:
        ch = market.snapshot(data[t], prices[t]) if t in data else {}
        material = [{k: m.get(k) for k in ("title", "summary", "source", "link", "materiality", "direction", "novelty", "event_type")} for m in mat]
        entry["investigator"] = desk.investigator(t, material, [f["title"] for f in st["news_feed"] if f["ticker"] == t][-15:], ch)
        sec = [m for m in material if m["source"] == "SEC filing"]
        if sec:
            entry["filings"] = desk.filings(t, sec)
        ctx = {"ticker": t, "held_trade": held, "armed_or_waiting_buy": st["candidates"].get(t),
               "investigator": entry["investigator"], "filings": entry.get("filings"), "chart": ch,
               "desk_memory_playbook": memory.playbook(st, t), "active_theses": active_theses(st, t),
               "rules": "You may SELL an open trade on clearly bad durable news, or SKIP to cancel a waiting buy. "
                        "BUY is not allowed: entries only happen at support levels."}
        entry["pm"] = desk.pm(ctx, "event")
        d = (entry["pm"].get("decisions") or {}).get(t, entry["pm"])
        if held or t in st["candidates"]:  # only argue when there is something to act on
            entry["risk"] = desk.challenge(t, d, {"held_trade": held, "waiting_buy": st["candidates"].get(t), "chart": ch})
            if entry["risk"].get("object"):
                entry["pm_reply"] = desk.pm({**ctx, "risk_manager_objection": entry["risk"], "reply_to": "Risk Manager",
                                             "instruction": "Reply to the Risk Manager's objection, then give your FINAL decision."}, "event")
                entry["pm"] = entry["pm_reply"]
    except Exception as e:
        entry["error"] = f"agent error: {e}"[:200]
        desk.record(entry)
        feed.say("system", f"The desk hit an error and did nothing: {e}"[:200])
        return
    d = (entry["pm"].get("decisions") or {}).get(t, entry["pm"])
    action = str(d.get("action", "HOLD")).upper()
    result = "no action"
    if action == "SELL" and held:
        if market.market_open():
            ex.exit_trade(t, prices[t], "agents: " + d.get("reason", "")[:120])
            result = "sold trade"
        else:
            account.lot(book, t, "trade")["exit_next_open"] = d.get("reason", "")[:120]
            result = "exit queued for the open"
    elif action in ("SKIP", "SELL") and t in st["candidates"]:
        st["candidates"].pop(t)
        ex_cancel(st, t)
        result = "canceled waiting buy"
    entry["result"] = result
    desk.record(entry)
    notify(f"Desk on {t}: {action} ({result})", (d.get("reason") or "")[:300], tags="brain")


# ======================================================================= intraday
def manage_open(st, ex, prices, today, brk_state):
    book = st["book"]
    for t in traded(st):
        L = account.lot(book, t, "trade")
        if L["qty"] <= 1e-6 or t not in prices:
            continue
        if brk_state["killed"]:
            ex.exit_trade(t, prices[t], "KILL SWITCH: account down 20% from peak"); continue
        if L.get("exit_next_open"):
            ex.exit_trade(t, prices[t], "agents (overnight decision): " + L.pop("exit_next_open")); continue
        if L.get("target") and prices[t] >= L["target"]:
            ex.exit_trade(t, prices[t], "target hit", tag="tp")
    if brk_state["killed"] and not st["flags"].get("kill_notified"):
        st["flags"]["kill_notified"] = True
        notify("KILL SWITCH", "Account is down 20% from its peak. Trades closed; set resume_after_kill to true to restart.",
               tags="rotating_light", priority="urgent")


def close_routine(st, desk, ex, data, prices, today, brk_state):
    import numpy as np
    book = st["book"]
    for t in traded(st):
        L = account.lot(book, t, "trade")
        if L["qty"] <= 1e-6:
            continue
        held = int(np.busday_count(dt.date.fromisoformat(L.get("opened", str(today))), today))
        if held >= L.get("max_days", 3):
            ex.exit_trade(t, prices[t], f"time limit ({held} days)")
    try:
        shadow_setups(st, data, prices, today)
    except Exception as e:
        print("shadow failed", e)
    if CFG.get("options_recorder", {}).get("enabled", True):
        try:  # before the close, while bids and asks are live
            rec = options_rec.record(CFG.get("options_recorder", {}).get("tickers") or T)
            snap = options_rec.put_call_snapshot(os.path.join(ROOT, rec["path"]))
            feed.post("options", f"Saved {sum(rec['contracts'].values()):,} option prices ({rec['files']} days on file). "
                      + " | ".join(f"{t}: put/call volume {v['pc_volume']}, open interest {v['pc_open_interest']}" for t, v in snap.items()),
                      T, kind="data", art={"big": f"{sum(rec['contracts'].values()):,} option prices saved", "sub": f"Day {rec['files']} of building our own options history"})
        except Exception as e:
            feed.post("system", f"Options recorder failed: {e}"[:200])


# ======================================================================= shadow setups (no money at risk)
def shadow_setups(st, data, prices, today):
    c = CFG["shadow_setups"]
    if not c["enabled"]:
        return
    sh = st.setdefault("shadow", [])
    for t in T:
        if t not in data:
            continue
        df = data[t]
        o, pc, cl = float(df.Open.iloc[-1]), float(df.Close.iloc[-2]), float(prices[t])
        gap = (o / pc - 1) * 100
        if gap <= c["gap_down_pct"]:
            lo, hi = float(df.Low.iloc[-1]), float(df.High.iloc[-1])
            stop, tgt = o * 0.97, pc
            r = (stop / o - 1) if lo <= stop else (tgt / o - 1) if hi >= tgt else (cl / o - 1)
            sh.append({"setup": "gap_down", "ticker": t, "date": str(today), "entry": round(o, 2), "done": True,
                       "ret_pct": round((r - 0.001) * 100, 2), "note": f"gap {gap:.1f}%"})
    del sh[:-500]


def shadow_summary(st):
    out = {}
    for x in st.get("shadow", []):
        if x.get("ret_pct") is None:
            continue
        g = out.setdefault(x["setup"], {"n": 0, "wins": 0, "sum": 0.0})
        g["n"] += 1; g["wins"] += x["ret_pct"] > 0; g["sum"] += x["ret_pct"]
    return {k: {"n": v["n"], "win_pct": round(v["wins"] / v["n"] * 100), "avg_ret_pct": round(v["sum"] / v["n"], 2)} for k, v in out.items()}


# ======================================================================= review
def evaluate_setups(st, data):
    """What would each armed/skipped setup have done (daily bars, stop-first)? Feeds the auditor."""
    for s in st["setup_log"]:
        if s.get("evaluated") or s["ticker"] not in data:
            continue
        after = data[s["ticker"]][data[s["ticker"]].index > s["date"]]
        if len(after) < 8:
            continue
        res, filled = None, False
        for _, r in after.head(8).iterrows():
            if not filled:
                if r.Low <= s["entry"]:
                    filled = True
                else:
                    continue
            if r.Low <= s["stop"]:
                res = s["stop"] / s["entry"] - 1; break
            if r.High >= s["target"]:
                res = s["target"] / s["entry"] - 1; break
        s["evaluated"], s["would_fill"] = True, filled
        s["would_ret_pct"] = round(res * 100, 2) if res is not None else (round((after.Close.iloc[7] / s["entry"] - 1) * 100, 2) if filled else None)


def grade_theses(st, prices):
    today = dt.date.today()
    for th in st.get("theses", []):
        if th.get("status") != "open":
            continue
        try:
            due = dt.date.fromisoformat(th.get("catalyst_date")) + dt.timedelta(days=3)
        except Exception:
            due = dt.date.fromisoformat(th["created"]) + dt.timedelta(days=30)
        if today >= due:
            moves = {t: round((prices[t] / p - 1) * 100, 2) for t, p in (th.get("start_prices") or {}).items() if t in prices}
            avg = sum(moves.values()) / len(moves) if moves else 0
            th["result_moves_pct"] = moves
            th["status"] = "right" if (th.get("direction") == "up" and avg > 0) or (th.get("direction") == "down" and avg < 0) \
                or (th.get("direction") == "volatile" and abs(avg) > 5) else "wrong"
            th["closed"] = str(today)


def scorecard(st):
    tr = st["book"]["trades"]
    by = {}
    for x in tr:
        g = by.setdefault(x["ticker"], {"n": 0, "wins": 0, "pnl": 0.0})
        g["n"] += 1; g["wins"] += x["pnl"] > 0; g["pnl"] = round(g["pnl"] + x["pnl"], 2)
    ev = [s for s in st["setup_log"] if s.get("evaluated") and s.get("would_fill")]
    avg = lambda xs: round(sum(x["would_ret_pct"] for x in xs) / len(xs), 2) if xs else None
    return {"by_ticker": by, "trades": len(tr), "pnl": round(sum(x["pnl"] for x in tr), 2),
            "skipped_setups_that_would_fill": len([s for s in ev if s["decision"] != "ARM"]),
            "skipped_avg_ret_pct": avg([s for s in ev if s["decision"] != "ARM"]),
            "armed_avg_ret_pct": avg([s for s in ev if s["decision"] == "ARM"]),
            "agent_cost_total": st.get("spend", {}).get("total_usd"), "agent_cost_by_role": st.get("spend", {}).get("by_role"),
            "shadow": shadow_summary(st), "ranking": st.get("ranking", {}).get("scores"),
            "strategist_theses": {"right": sum(1 for x in st.get("theses", []) if x.get("status") == "right"),
                                  "wrong": sum(1 for x in st.get("theses", []) if x.get("status") == "wrong")}}


def review(st, desk, data, prices, today, brk_state):
    book = st["book"]
    b = st["benchmark"]
    if b["shares"] is None:
        b["shares"] = {"SPY": CFG["capital_cap"] / prices["SPY"]}
    bh = sum(b["shares"][t] * prices.get(t, 0) for t in b["shares"])
    b["equity"].append([str(today), round(bh, 2)])
    eq = account.equity(book, prices)
    book["equity"].append([str(today), round(eq, 2), round(account.core_value(book, prices), 2), round(account.trade_value(book, prices), 2)])
    evaluate_setups(st, data)
    memory.fill_reactions(st, data)
    grade_theses(st, prices)
    officer = {"settled_cash": round(account.settled_cash(book, today), 2), "cash": round(book["cash"], 2),
               "realized_short_term_gains": book["realized_st"], "wash_sale_flags": book["wash_flags"][-5:], "brakes": brk_state}
    try:
        real = BROKER["b"].positions()
        mism = {t: {"bot": round(sum(l["qty"] for l in book["lots"].get(t, {}).values()), 4), "broker": round(real.get(t, {}).get("qty", 0), 4)}
                for t in set(list(real) + list(book["lots"]))}
        officer["position_mismatch"] = {t: v for t, v in mism.items() if abs(v["bot"] - v["broker"]) > 0.001}
        if officer["position_mismatch"]:
            notify("Books don't match broker", json.dumps(officer["position_mismatch"])[:250], tags="warning")
    except Exception as e:
        officer["position_mismatch"] = f"check failed: {e}"[:120]
    st["officer"] = officer
    packet = {"date": str(today), "weekday": today.strftime("%A"), "goal": "+5% per week (not forced)", "lineup": T,
              "equity": round(eq, 2), "start": CFG["capital_cap"], "spy_buy_and_hold": round(bh, 2),
              "week_pct": brk_state["week_pct"], "day_pct": brk_state["day_pct"],
              "open_trades": {t: account.lot(book, t, "trade") for t in traded(st) if account.lot(book, t, "trade")["qty"] > 1e-6},
              "armed": st["armed"], "waiting": {t: c for t, c in st["candidates"].items() if t not in st["armed"]},
              "trades_closed_today": [x for x in book["trades"] if str(x.get("exit_time", "")).startswith(str(today))],
              "orders_today": [o for o in st["orders_log"] if o["time"].startswith(str(today))],
              "desk_today": [{k: e.get(k) for k in ("ticker", "trigger", "result", "headline")} for e in st.get("desk_log", [])
                             if e.get("time", "").startswith(str(today))], "officer": officer}
    try:
        sh = shadow.run_daily(st)
        if sh.get("new"):
            feed.post("shadow", ("First run: replayed the last 60 days. " if sh.get("backfill") else "") +
                      f"{sh['new']} practice trades closed: {sh['wins']} wins, {sh['new'] - sh['wins']} losses, "
                      f"{sh['sumR']:+.2f}R in total (R = what one trade risks). Best: {sh['best']}. {sh['total']:,} practice trades on record.", kind="data",
                      art={"big": f"{sh['new']:,} practice trades", "sub": f"{sh['wins']} won, {sh['new'] - sh['wins']} lost, {sh['sumR']:+.1f}R. No money involved."})
        else:
            feed.post("shadow", "No practice trades closed today.", kind="data")
    except Exception as e:
        feed.post("system", f"Shadow desk failed: {e}"[:200])
    if today.weekday() == 4:
        try:
            lr = shadow.learn_report(st)
            st["learn_report"] = lr
            if lr["status"] == "collecting":
                feed.post("shadow", f"Weekly lessons: still collecting ({lr['n']} practice trades; patterns need 120+).", kind="learn")
            else:
                pats = "; ".join(f"{p['what']} {p['direction']} ({p['older_vs_avg_R']:+.2f}R then {p['newer_vs_avg_R']:+.2f}R, n={p['n']})"
                                 for p in lr["patterns"]) or "nothing held up in both halves"
                feed.post("shadow", f"Weekly lessons from {lr['n']:,} practice trades (avg {lr['avg_R']:+.3f}R): {pats}. "
                          "These are candidates; each still needs a written-rule test.", kind="learn",
                          art={"big": "This week's lessons", "sub": f"{len(lr['patterns'])} pattern(s) held up twice. Still unproven."})
        except Exception as e:
            feed.post("system", f"Learn report failed: {e}"[:200])
    if today.weekday() == 4:  # feedback loop: is each live signal still behaving like its research said?
        try:
            dr = signals.weekly_drift(st)
            packet["signal_drift"] = dr
            nice = {"asia_gap_nowcast": "Asia nowcast", "patient_levels": "The strategy"}
            stat = {"healthy": "working as researched", "weakening": "weakening", "broken": "broken", "collecting": "still collecting trades"}
            feed.post("drift", "Weekly check against the research: " + "; ".join(f"{nice.get(k, k)}: {stat.get(v.get('status'), v.get('status'))}"
                      + (f" (link to the open {v['avg_corr']})" if v.get('avg_corr') is not None else "")
                      + (f" ({v['n']} trades)" if v.get('n') else "") for k, v in dr["signals"].items()) + ".", kind="data",
                      art={"big": "Weekly check: " + ("all healthy" if all(v.get("status") in ("healthy", "collecting") for v in dr["signals"].values()) else "something slipped"),
                           "sub": "Live results compared with what the research promised"})
            bad = {k: v["status"] for k, v in dr["signals"].items() if v.get("status") in ("weakening", "broken")}
            if bad:
                notify("Signal drift", ", ".join(f"{k}: {v}" for k, v in bad.items())
                       + ". Check research/signals_registry.json retire rules.", tags="chart_with_downwards_trend")
        except Exception as e:
            print("drift check failed", e)
    with feed.thread(f"Daily review {today:%a %b %d}" + (" + weekly strategy" if today.weekday() == 4 else ""), T, kind="review"):
        closed = [x for x in book["trades"] if str(x.get("exit_time", "")).startswith(str(today))]
        feed.say("officer", f"Numbers for the reviewer: account ${eq:,.2f} vs ${CFG['capital_cap']:,.0f} start, "
                 f"{brk_state['week_pct']:+.2f}% this week; the S&P buy-and-hold would be at ${bh:,.2f}. "
                 f"{len(closed)} trade(s) closed today. Settled cash ${officer['settled_cash']:,.2f}.")
        rev = None
        if desk.available:
            try:
                rev = desk.reviewer(packet, weekly=today.weekday() == 4)
                if today.weekday() == 4:
                    ch = learning.update_weights(st, CFG, today) if CFG["learning"]["enabled"] else {}
                    sc = scorecard(st)
                    sc["learning"] = ch
                    sc["postmortem_verdicts"] = {v: sum(1 for p in st.get("postmortems", []) if p.get("verdict") == v)
                                                 for v in ("bad_setup", "bad_execution", "regime_mismatch", "news_shock", "noise")}
                    au = desk.auditor(sc)
                    try:
                        sg = desk.strategist({"date": str(today), "lineup": T, "watchlist": CFG["watchlist"],
                                              "memory_playbook": {t: memory.playbook(st, t) for t in T},
                                              "material_news": [{k: e[k] for k in ("ticker", "type", "title", "date", "r1", "r5")}
                                                                for e in st.get("event_memory", [])][-60:],
                                              "intel_trends": dict(list(st.get("intel_history", {}).items())[-20:]),
                                              "open_theses": active_theses(st), "graded_theses": [x for x in st.get("theses", []) if x.get("status") != "open"][-10:],
                                              "calendar": (st.get("brief") or {}).get("calendar"), "radar": st.get("radar")})
                        for th in (sg.get("theses") or [])[:3]:
                            th.update(created=str(today), status="open", start_prices={t: round(prices[t], 2) for t in th.get("tickers", []) if t in prices})
                            st.setdefault("theses", []).append(th)
                            if th.get("conviction") == "high":
                                notify(f"Strategist: {', '.join(th.get('tickers', []))} ({th.get('direction')})",
                                       f"{th.get('thesis', '')[:180]} Catalyst: {th.get('catalyst', '')[:60]} {th.get('catalyst_date', '')}.", tags="crystal_ball")
                        st["theses"] = st.get("theses", [])[-60:]
                        st["strategy_note"] = sg.get("summary")
                    except Exception as e:
                        print("strategist failed", e)
                    st["audits"].append({"date": str(today), "scorecard": sc, "auditor": au})
                    del st["audits"][:-20]
            except Exception as e:
                print("review failed", e)
    headline = (rev or {}).get("headline") or f"Account ${eq:.2f} ({brk_state['week_pct']:+.2f}% this week)"
    st["reviews"].append({"date": str(today), "headline": headline, "markdown": (rev or {}).get("review_markdown") or "_Agents off: numbers only._",
                          "equity": round(eq, 2), "bh": round(bh, 2), "week_pct": brk_state["week_pct"]})
    del st["reviews"][:-60]
    if CFG["notify"]["daily_review"]:
        notify("Daily review", f"{headline} | week {brk_state['week_pct']:+.2f}% vs +5% goal | SPY hold ${bh:.2f}", tags="memo")
    try:
        if CFG["promotion_gate"]["enabled"]:
            before = (st.get("gate") or {}).get("passed")
            st["gate"] = gate.evaluate(st, CFG)
            if st["gate"].get("passed") and not before:
                notify("Promotion gate PASSED", f"Paper record: Deflated Sharpe {st['gate']['dsr']} over {st['gate']['days']} days, "
                       f"worst drop {st['gate']['maxdd_pct']}%. Live trading is now allowed by the gate.", tags="trophy", priority="high")
    except Exception as e:
        print("gate failed", e)


# ======================================================================= cycle
def cycle(st, desk, br, ex, force=()):
    now = market.now_et()
    today = now.date()
    if (now.weekday() == 0 and now.time() >= dt.time(8, 0)) or "rank" in force or not st.get("ranking"):
        weekly_rank(st, force="rank" in force)
    T[:] = st["active"]
    tick = traded(st)
    data, prices = market.fetch(tick + ["SPY"])
    st["last_prices"], st["last_cycle"] = {t: round(prices[t], 2) for t in tick + ["SPY"]}, now.strftime("%Y-%m-%d %H:%M ET")
    book = st["book"]
    is_open = market.market_open() or "close" in force or "morning" in force
    if is_open:
        process_fills(st, br, ex, today)
    brk_state = account.brakes(book, prices, CFG, today)
    if not ops.check(st, CFG, notify, prices, brk_state["equity"], book["lots"], market.INTRADAY, market.market_open()):
        brk_state["no_new_today"], brk_state["ops_halt"] = True, True
    if not gate.live_entries_allowed(st, CFG, br.name):
        brk_state["no_new_today"], brk_state["gate_block"] = True, True
        notify_once(st, "gate_block", "Live buys blocked by the promotion gate",
                    "The paper record hasn't passed yet (Deflated Sharpe, net-of-cost halves, drawdown). Exits and stops "
                    "still run. Set live_override true in config.json to trade live anyway.")
    st["brakes"] = brk_state
    if market.market_open() or not st.get("equity_intraday"):  # the home-screen chart
        ei = st.setdefault("equity_intraday", [])
        ei.append([now.strftime("%Y-%m-%d %H:%M"), round(brk_state["equity"], 2)])
        del ei[:-4000]
    if is_open:
        if (st["flags"].get("morning_done") != str(today) and now.time() >= dt.time(9, 31)) or "morning" in force:
            st["flags"]["morning_done"] = str(today)
            morning(st, desk, br, ex, data, prices, today, brk_state)
            process_fills(st, br, ex, today)
        manage_open(st, ex, prices, today, brk_state)
        process_fills(st, br, ex, today)
        try:
            refresh_candidates(st, desk, data, prices, today, brk_state)
            arm(st, ex, prices, today, brk_state)
            process_fills(st, br, ex, today)
        except Exception as e:
            traceback.print_exc()
    hawk_events(st)
    handle_owner_posts(st, desk, ex, data, prices, today, brk_state)
    handle_news(st, desk, ex, data, prices, today, brk_state)
    if ((now.weekday() < 5 and dt.time(15, 40) <= now.time() <= dt.time(15, 58)) or "close" in force) \
            and st["flags"].get("close_done") != str(today):
        st["flags"]["close_done"] = str(today)
        close_routine(st, desk, ex, data, prices, today, brk_state)
        process_fills(st, br, ex, today)
    if ((now.weekday() < 5 and dt.time(16, 5) <= now.time() <= dt.time(19, 0)) or "review" in force) \
            and st["flags"].get("review_done") != str(today):
        st["flags"]["review_done"] = str(today)
        review(st, desk, data, prices, today, account.brakes(book, prices, CFG, today))
    for k in [k for k in st["flags"] if ":" in k and k.split(":")[-1][:10] < str(today - dt.timedelta(days=10))]:
        del st["flags"][k]
    os.makedirs(os.path.join(ROOT, "orders"), exist_ok=True)
    json.dump({"date": str(today), "broker": br.name, "orders": [o for o in st["orders_log"] if o["time"].startswith(str(today))]},
              open(os.path.join(ROOT, "orders", "today.json"), "w"), indent=1)


def main():
    args = sys.argv[1:]
    st = load_state()
    desk = Desk(CFG, st)
    DESK["d"] = desk
    if os.environ.get("GITHUB_ACTIONS") and CFG.get("runner") == "vm" and args and args[0] in ("loop", "once"):
        print("runner is 'vm': GitHub run skipped so two copies never trade at once"); return
    br = brk.make(CFG, st)
    BROKER["b"] = br
    st["broker"] = br.name
    ex = Exec(st, br)
    force = tuple(a.replace("--force-", "") for a in args if a.startswith("--force-"))
    if args and args[0] == "owner-post":
        import time as _t
        inbox.LOCAL.append({"id": f"local-{_t.time():.0f}", "time": _t.time(), "text": " ".join(a for a in args[1:] if not a.startswith("--"))[:500]})
        cycle(st, desk, br, ex, force)
    elif not args or args[0] == "once":
        cycle(st, desk, br, ex, force)
    elif args[0] == "loop":
        minutes = float(args[args.index("--minutes") + 1]) if "--minutes" in args else 13
        end = time.time() + minutes * 60
        while True:
            try:
                cycle(st, desk, br, ex)
            except Exception as e:
                traceback.print_exc()
                notify_once(st, "cycle_error", "Desk cycle error", str(e)[:250])
            save_state(st)
            if time.time() + CFG["poll_seconds"] > end:
                break
            time.sleep(CFG["poll_seconds"])
    elif args[0] == "daemon":
        import threading
        last_push, last_dash = 0, 0
        wake = threading.Event()
        if br.name.startswith("alpaca"):
            def stream():
                try:
                    from alpaca.trading.stream import TradingStream
                    ts = TradingStream(os.environ["ALPACA_KEY"], os.environ["ALPACA_SECRET"], paper=br.paper)

                    async def on_update(data):
                        if getattr(data, "event", "") in ("fill", "partial_fill", "rejected", "canceled"):
                            wake.set()
                    ts.subscribe_trade_updates(on_update)
                    ts.run()
                except Exception as e:
                    print("trade stream stopped", e)
            threading.Thread(target=stream, daemon=True).start()
            if CFG.get("hawk", {}).get("stream_prices"):
                threading.Thread(target=hawk_stream, args=(st, wake), daemon=True).start()
        notify("Swing Desk online", f"Always-on mode started ({br.name}). Hawk mode: live prices, news every minute.", tags="green_heart")
        while True:
            now = market.now_et()
            active = now.weekday() < 5 and dt.time(8, 0) <= now.time() <= dt.time(19, 0)
            if active:
                try:
                    cycle(st, desk, br, ex)
                except Exception as e:
                    traceback.print_exc()
                    notify_once(st, "cycle_error", "Desk cycle error", str(e)[:250])
                save_state(st)
                if time.time() - last_dash > 300:
                    dashboard.build(st, CFG); last_dash = time.time()
                if os.environ.get("AUTO_GIT") == "1" and time.time() - last_push > 900:
                    os.system(f"cd {ROOT} && git add -A state.json docs orders data >/dev/null 2>&1 && "
                              f"git commit -qm 'desk {now:%F %H:%M}' >/dev/null 2>&1; git push -q >/dev/null 2>&1")
                    last_push = time.time()
            wake.wait(CFG.get("daemon_poll_seconds", 60) if active else 300)
            wake.clear()
    elif args[0] == "test-notify":
        t = ntfy_topic()
        if not t:
            print("NTFY_TOPIC secret is empty or missing."); sys.exit(1)
        print(f"Sending to topic: {t[:3]}{'*' * max(len(t) - 3, 0)} ({len(t)} characters)")
        notify("Swing Desk connected", "Phone alerts work: lineup, armed orders, fills, news, morning brief, daily review.")
        if NOTIFY_ERR:
            print("Sending failed:", NOTIFY_ERR[-1]); sys.exit(1)
        print("Sent. If your phone got nothing, the ntfy app is subscribed to a different name (names are case-sensitive).")
        return
    elif args[0] == "test-agents":
        print(desk.ask("technical", "fast", 'Reply {"ok":true}', "ping", max_tokens=30))
        save_state(st); return
    elif args[0] == "test-broker":
        print(br.name, br.account(), br.positions(), br.open_orders()[:5])
        return
    save_state(st)
    dashboard.build(st, CFG)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        notify("Swing Desk ERROR", str(e)[:300], tags="warning", priority="high")
        raise
