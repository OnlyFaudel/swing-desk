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
import sys, json, os, re, time, traceback, datetime as dt
import urllib.request

import gate, signals, feed, shadow, options_rec, inbox, research_lab, desk_memory, collector, reactors, archive, discovery, dossier, jobs, peers, world, uprice, congress, price_events, people, notes, plant, optspec, sput, catalysts, redteam, earnings, weekly, weather, shocks, licenses, deals, radarlog, watchdog, market, news, intel, account, learning, ops, memory, patient, broker as brk, dashboard
from agents import Desk, Budget, MOCK

ROOT = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(ROOT, "config.json")))
STATE_PATH = os.path.join(ROOT, "state.json")
T = []          # this week's lineup (set every cycle from state["active"])
BROKER, DESK = {}, {}


# ======================================================================= plumbing
def unleashed():
    """Paper-only freedom: true unless the broker is a LIVE account (then every limit is back on)."""
    b = BROKER.get("b")
    return bool(CFG.get("paper_unleashed", {}).get("enabled")) and not (b and b.name.upper().endswith("LIVE"))


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
        h = {"Title": title.encode("ascii", "ignore").decode(), "Tags": tags, "Priority": priority}
        if os.environ.get("NTFY_TOKEN", "").strip():  # your own ntfy account: limits are yours, not the shared GitHub machine's
            h["Authorization"] = "Bearer " + os.environ["NTFY_TOKEN"].strip()
        req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode(), headers=h)
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
    held = [t for t, l in st["book"]["lots"].items() if any(l.get(k, {}).get("qty", 0) > 1e-6 for k in ("trade", "panic", "auto"))]
    return list(dict.fromkeys(T + held + list(st["armed"])))


def spy_px(st):
    live = market.LIVE.get("SPY")
    return (live[0] if live and time.time() - live[1] < 600 else None) or (st.get("last_prices") or {}).get("SPY")


def free_cash(st, today):
    return account.settled_cash(st["book"], today) - sum(a.get("dollars", 0) for a in st["armed"].values())


def spendable(st, today):
    """Cash we can put into a trade right now: free cash plus the parked S&P shares (sold on demand)."""
    px = spy_px(st)
    return free_cash(st, today) + (account.park_value(st["book"], {"SPY": px}) if px else 0)


# ======================================================================= execution trader (code)
class Exec:
    def __init__(self, st, br):
        self.st, self.br = st, br

    def ensure_cash(self, need):
        """Idle money sits in the S&P (SPY). When a trade needs it, sell just enough SPY first."""
        today = market.now_et().date()
        short = need - free_cash(self.st, today)
        L = self.st["book"]["lots"].get("SPY", {}).get("park", {})
        px = spy_px(self.st)
        if short <= 0 or not L.get("qty") or not px:
            return
        qty = min(L["qty"], round(short * 1.01 / px, 6))
        try:
            log_order(self.st, self.br.market_sell("SPY", qty, px, "pkx"), f"sold ${qty * px:.0f} of parked S&P to fund a trade")
            time.sleep(0 if self.br.name == "sim" else 2)
            process_fills(self.st, self.br, self, today)
        except Exception as e:
            ops.note_reject(self.st, CFG, notify, f"SPY parking sale: {e}")

    def buy_limit(self, t, qty, limit, tag, meta, note):
        self.ensure_cash(qty * limit)
        try:
            o = self.br.limit_buy(t, qty, limit, tag)
        except Exception as e:
            ops.note_reject(self.st, CFG, notify, f"{t} {tag}: {e}")
            return None
        ops.note_order(self.st, CFG, notify)
        self.st["pending_meta"][o["client_id"]] = meta
        log_order(self.st, o, note)
        return o

    def buy_market(self, t, notional, price, tag, meta, note):
        if tag != "pk":
            self.ensure_cash(notional)
        try:
            o = self.br.market_buy(t, notional, price, tag)
        except Exception as e:
            ops.note_reject(self.st, CFG, notify, f"{t} {tag}: {e}")
            return None
        ops.note_order(self.st, CFG, notify)
        self.st["pending_meta"][o["client_id"]] = meta
        log_order(self.st, o, note)
        return o

    def exit_panic(self, t, price, reason, kind="panic", tag="prx"):
        L = account.lot(self.st["book"], t, kind)
        if L["qty"] <= 1e-6 or L.get("selling") == str(dt.date.today()):
            return
        L["exit_reason"], L["selling"] = reason, str(dt.date.today())
        try:
            log_order(self.st, self.br.market_sell(t, L["qty"], price, tag), reason)
        except Exception as e:
            notify(f"EXIT FAILED {t}", f"{reason}: {str(e)[:150]}", tags="rotating_light", priority="high")

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
        elif tag == "pr" and f["side"] == "buy" and CFG["notify"]["trades"]:
            L = account.lot(book, f["symbol"], "panic")
            notify(f"BOUGHT {f['symbol']} (panic-day rebound)", f"{f['qty']:.4f} sh @ ${f['fill_price']:.2f} = ${f['qty'] * f['fill_price']:.2f} | "
                   f"sell near the close on {L.get('exit_on')} | {L.get('why', '')[:90]}", tags="zap")
        elif tag.startswith("core") and CFG["notify"]["trades"]:
            notify(f"CORE {f['side'].upper()} {f['symbol']}", f"{f['qty']:.4f} sh @ ${f['fill_price']:.2f}", tags="moneybag")
        if rec:
            if CFG["notify"]["trades"]:
                notify(f"SOLD {rec['ticker']} {'+' if rec['pnl'] >= 0 else ''}{rec['ret']:.1f}%",
                       f"P&L {'+' if rec['pnl'] >= 0 else '-'}${abs(rec['pnl']):.2f} | {rec['why_out']}",
                       tags="green_circle" if rec["pnl"] >= 0 else "red_circle")
            postmortem(st, rec)
            st.setdefault("after_sale", []).append({"ticker": rec["ticker"], "exit": rec["exit"], "date": str(today),
                                                   "pnl": rec["pnl"], "why_out": rec.get("why_out"), "setup": rec.get("setup")})


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
    if pm.get("lesson") and str(pm["lesson"]).lower() != "none":
        st.setdefault("lessons", []).append({"date": entry["date"], "kind": "closed_trade", "title": f"{rec['ticker']} trade {rec['pnl']:+.2f}",
                                             "lesson": pm["lesson"], "cause": pm.get("verdict")})
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
            notify("Lineup", f"The nuclear fuel chain{' (paper: as many trades as setups and cash allow)' if unleashed() else ', 3 trades at a time'}: {', '.join(st['active'])}. "
                   "Practice trades keep running on 52 stocks.", tags="trophy")
        return
    st["active"] = list(CFG["always_include"]) + picks
    st["ranking"] = {"week": wk, "date": str(dt.date.today()), "scores": r, "active": st["active"]}
    notify("This week's lineup", f"{', '.join(st['active'])} (was {', '.join(old) or 'none'}). Top by how Patient Levels "
           f"worked on each over the last {CFG['rank_weeks']} weeks: " +
           ", ".join(f"{t} {v['score']:+.2f}%" for t, v in list(r.items())[:5]), tags="trophy")


# ======================================================================= candidates + arming (the one strategy)
def sessions_after(d0, n):
    """n trading sessions after d0, skipping weekends AND market holidays (Thanksgiving, Christmas...)."""
    try:
        import exchange_calendars as xc
        import pandas as pd
        cal = xc.get_calendar("XNYS")
        start = cal.date_to_session(pd.Timestamp(d0), direction="next")
        return str(cal.sessions_window(start, n + 1)[-1].date())
    except Exception:
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
        broke = prices.get(t) is not None and prices[t] <= c["stop"]  # price fell through the level: that setup is dead
        if str(today) > c["valid_until"] or t not in T or broke:
            st["candidates"].pop(t)
            if t in st["armed"]:
                ex_cancel(st, t, "expired")
            if broke:
                st.setdefault("setup_status", {})[t] = (f"its support at ${c['zone']} broke (now ${prices[t]:.2f}, under the "
                                                        f"${c['stop']} stop), so that setup was dropped; waiting for a new level")
                st.setdefault("last_scan", {}).pop(t, None)
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
        vp = patient.volume_profile(h, s["entry"])
        if vp:
            s["volume"] = vp
            if vp["skip"] and P.get("volume_filter", True):
                why[t] = (f"a level at ${s['zone']} but it sits {'below where most shares traded' if vp['position'] == 'below value' else 'in a thin, low-volume zone'} "
                          "over the last 20 sessions; levels like that averaged nothing in 9,877 practice trades, so it sits out")
                st.setdefault("vp_skipped", []).append({"date": str(today), "ticker": t, **{k: s[k] for k in ("zone", "entry", "stop", "target")}, "vp": vp})
                del st["vp_skipped"][:-200]
                continue
        why[t] = "setup found"
        decision, reason = "ARM", "rules (agents off)"
        if desk.available:
            try:
                lv = desk.level_trader({t: s}, {"strategy": "Patient Levels: order rests up to 5 sessions, max hold 3 days",
                                                "morning_intel": {k: (st.get("morning") or {}).get(k) for k in ("whale", "crowd", "macro")},
                                                "chart": market.snapshot(data[t], prices[t]), "lessons_from_past_trades": lessons(st),
                                                "research_notebook": research_lab.highlights(st),
                                                "this_stock_recent_events": [e for e in desk_memory.events() if e["ticker"] == t
                                                                             and e["date"] >= str(today - dt.timedelta(days=45))][-6:],
                                                "what_share_offerings_did_before": desk_memory.playbook("offering_dilution", list(T)),
                                                "desk_memory_playbook": memory.playbook(st, t), "active_theses": active_theses(st, t),
               "everything_we_know": dossier.for_agent(t), "discoveries": discovery.brief(5),
                                                "everything_we_know": dossier.for_agent(t), "discoveries": discovery.brief(5),
                                                "recent_headlines": [f["title"] for f in st["news_feed"] if f["ticker"] == t][-8:]})
                v = (lv.get("setups") or {}).get(t, {})
                said = str(lv.get("say") or "")
                d0 = v.get("decision") or lv.get("decision") or ("SKIP" if re.search(r"\bskip", said, re.I) else "ARM")
                decision, reason = str(d0).upper(), v.get("reason") or lv.get("reason") or said[:200]
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


def ex_cancel(st, t, why="rule"):
    a = st["armed"].pop(t, None)
    if a and why != "expired":  # a buy a rule or the team canceled: watched to see if it would have won
        st.setdefault("cancels", []).append({"ticker": t, "entry": a.get("entry"), "stop": a.get("stop"), "target": a.get("target"),
                                             "date": str(market.now_et().date()), "valid_until": a.get("valid_until") or str(market.now_et().date()),
                                             "why": why})
    if a:
        BROKER["b"].cancel(a["order_id"])


def arm(st, ex, prices, today, brk_state):
    """Keep resting buy orders on the candidates most likely to fill, as many as free slots and settled cash allow."""
    book = st["book"]
    if brk_state["killed"] or brk_state.get("ops_halt") or brk_state["no_new_today"] or brk_state["no_new_week"]:
        for t in list(st["armed"]):
            ex_cancel(st, t, "loss brakes")
        return
    open_trades = [t for t in traded(st) if account.lot(book, t, "trade")["qty"] > 1e-6]
    eq = brk_state["equity"]
    if unleashed():  # no fixed number of trades: every setup gets an order while settled cash lasts
        free = len(T)
        slot_usd = eq * CFG["paper_unleashed"]["trade_size_pct"] / 100 * learning.mult(st, "patient_level") * brk_state["risk_mult"]
    else:
        free = CFG["slots"] - len(open_trades)
        slot_usd = min(eq / CFG["slots"], eq * CFG["max_position_pct"] / 100) * learning.mult(st, "patient_level") * brk_state["risk_mult"]
    try:
        st["sync"] = sync_state(st, market.fetch_hourly(T))
    except Exception as e:
        st["sync"] = {"mult": {}, "error": str(e)[:120]}
    if CFG["sync"].get("pulse_filter") and st["sync"].get("pulse_up") is False:  # applies on paper too: tested 2026-11-23, buys in a falling sector lose
        for t in list(st["armed"]):
            ex_cancel(st, t, "falling-sector rule")
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
    av = st.get("avoid", {})  # a discovery says this kind of news hurts this stock: no support-level buys until the date
    cands = [(c, t) for c, t in cands if av.get(t, {}).get("until", "") < str(today)]
    want = [t for c, t in cands][:max(free, 0)]
    for t in list(st["armed"]):
        if t not in want:
            ex_cancel(st, t, "ranking (a better setup took the slot)")
    cash = spendable(st, today)
    for c, t in cands:
        if t not in want or t in st["armed"]:
            continue
        sm = st["sync"].get("mult", {}).get(t, 1.0)
        fv = st.get("favor", {}).get(t, {})
        if fv.get("until", "") >= str(today):
            sm *= fv.get("mult", 1.0)  # a discovery favors this stock for a few days
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
    try:
        radarlog.log(res, prices)
    except Exception as e:
        print("radar log", e)


# ======================================================================= morning
def morning_prep(st, desk, data, prices, today, brk_state):
    """9:00 ET: the full morning meeting BEFORE the bell. Nowcast, brief, options radar, macro/whales/crowd and the
    Level Analyst's setups are all done here, so at 9:31 the bot only has to check the real opening prices and place orders."""
    book = st["book"]
    with feed.thread(f"Morning meeting {today:%a %b %d}", T, kind="morning"):
        held_now = [t for t in traded(st) if account.lot(book, t, "trade")["qty"] > 1e-6]
        feed.say("chief", f"Morning, team. The bell is at 9:30; let's be ready before it. Lineup {', '.join(T)}. Account ${brk_state['equity']:,.2f}, "
                 f"{brk_state['week_pct']:+.2f}% this week. Open trades: {', '.join(held_now) or 'none'}. "
                 "Nowcast first, then macro, whales and the crowd; the Level Analyst picks the buys. Orders go in once the open prints.")
        nc_line = ""
        try:  # Asia's close -> expected opening gap (information only; research/ccj_leadlag.py)
            if st.get("nowcast_date") != str(today) or not any(isinstance(v, dict) and v.get("expected_gap_pct") is not None
                                                                for v in (st.get("nowcast") or {}).values()):
                st["nowcast"] = signals.nowcast(T)
                st["nowcast_date"] = str(today)
            g = [f"{t} {v['expected_gap_pct']:+.1f}%" for t, v in st["nowcast"].items() if isinstance(v, dict) and v.get("expected_gap_pct") is not None]
            nc_line = (" | Asia says open: " + ", ".join(g)) if g else ""
            feed.say("nowcast", ("Asia's close points to these opens: " + ", ".join(g) + ". That's priced in at 9:30, so treat it as context, not a trade.") if g else "No fresh Asia close yet.")
            if g:
                feed.post("nowcast", "Asia's close points to these opens: " + ", ".join(g) + ". Information only: the open prices this in, "
                          "so it never places a trade.", T, kind="data", art={"big": "Asia says: " + ", ".join(g), "sub": "Expected opening moves. Background only."})
        except Exception as e:
            st["nowcast"] = {"error": str(e)[:120]}
        earnings = {t: market.next_earnings(t) for t in T}
        b = intel.morning_brief(tcfg(st), st.setdefault("cache", {}), prices, earnings)
        st["brief"] = b
        record_intel(st, b, today)
        run_radar(st, prices, earnings)
        mo = {"date": str(today), "prepped": True, "nc_line": nc_line}
        if desk.available:
            try:
                mo["macro"] = desk.macro({**(b.get("market") or {}), "research_notebook": research_lab.highlights(st)}, b.get("calendar"))
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
        waiting = {t: c["entry"] for t, c in st["candidates"].items()}
        feed.say("chief", "Ready for the bell. " + (("Buys to place at 9:31 if the open is still above support: "
                 + ", ".join(f"{t} ${p}" for t, p in waiting.items()) + ".") if waiting else "No safe buys yet; we watch the open."))
    m = mo.get("macro") or {}
    notify("Morning meeting done", f"Ready before the bell | risk {m.get('risk_level', 'n/a')} | buys planned: "
           + (", ".join(f"{t} ${p}" for t, p in waiting.items()) or "none") + nc_line, tags="sunrise", who="chief")


def morning(st, desk, br, ex, data, prices, today, brk_state):
    """9:31 ET: the open has printed. Re-place stops, drop setups the open already broke, place the planned buys."""
    book = st["book"]
    if br.name == "sim":
        br.expire_day_orders()
    st["pending_meta"], st["armed"] = {}, {}
    for t in traded(st):  # re-place DAY stops
        L = account.lot(book, t, "trade")
        if L["qty"] > 1e-6 and L.get("stop"):
            ex.place_stop(t, L["stop"])
    if (st.get("morning") or {}).get("date") != str(today) or not st["morning"].get("prepped"):
        morning_prep(st, desk, data, prices, today, brk_state)  # the 9:00 meeting was missed (restart): do it now
    mo = st["morning"]
    for t in traded(st):  # don't hold a trade through earnings
        d = market.trading_days_until(market.next_earnings(t))
        if d is not None and 0 <= d <= CFG["exit_trading_before_earnings_days"] and account.lot(book, t, "trade")["qty"] > 1e-6:
            ex.exit_trade(t, prices[t], f"earnings {market.next_earnings(t)}: not holding a trade through it")
    refresh_candidates(st, desk, data, prices, today, brk_state)  # drops any setup the opening print already broke
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
               + f" | waiting: {', '.join(t for t in st['candidates'] if t not in st['armed']) or 'none'}" + (mo.get("nc_line") or ""), tags="sunrise")


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
        return []
    import re
    raw = list(dict.fromkeys(HAWK_EVENTS)); HAWK_EVENTS.clear()
    st["news_slow_at"] = 0
    now, et = time.time(), market.now_et()
    thr = CFG["hawk"]["move_alert_pct"]
    mine = set(traded(st)) | set(st.get("armed") or {})  # stocks we hold or have an order on: always worth a look
    recent = [x for x in st.get("hawk_recent", []) if now - x[0] < 900]
    cool = st.setdefault("hawk_cool", {})
    opening = dt.time(9, 30) <= et.time() < dt.time(9, 45)  # the first 15 minutes are always jumpy: only big moves count
    ev = []
    for e in raw:
        m = re.match(r"(\w+) moved ([+-][\d.]+)%", e)
        if not m:
            ev.append(e); continue  # target touches and anything else always pass
        t, pct = m.group(1), float(m.group(2))
        recent.append((now, t, 1 if pct > 0 else -1))
        big = abs(pct) >= 2 * thr
        if t in mine or big:
            ev.append(e); continue
        if opening or now < st.get("hawk_sector_until", 0) or now - cool.get(t, 0) < 1200:
            continue
        cool[t] = now
        ev.append(e)
    st["hawk_recent"] = recent
    for sign in (1, -1):
        names = sorted({t for _, t, s in recent if s == sign})
        if len(names) >= 4 and now >= st.get("hawk_sector_until", 0):
            st["hawk_sector_until"] = now + 1800
            word = "up" if sign > 0 else "down"
            msg = f"sector move: {len(names)} of our nuclear stocks moving {word} together ({', '.join(names)})"
            ev = [x for x in ev if not any(x.startswith(t + " moved") for t in names if t not in mine)] + [msg]
    if not ev:
        return []
    feed.post("chief", "Hawk alert: " + "; ".join(ev) + ". Checking the news for a reason.",
              [t for t in T if any(t in e for e in ev)], kind="alert",
              art={"big": ev[0], "sub": "Live price alert. The team is checking the news."})
    return ev


# ======================================================================= desk memory (long-term)
def memory_daily(st, data=None):
    if not any(e.get("source") == "SEC (backfill)" for e in desk_memory.events()):  # not "if empty": news events can arrive first
        n = desk_memory.backfill_sec(list(T))
        feed.post("researcher", f"Loaded {n:,} company events from SEC filings since 2019 into the desk's long-term memory "
                  "(contracts, earnings, share offerings, leadership changes), with what each stock did afterwards.", kind="learn",
                  art={"big": f"{n:,} past events remembered", "sub": "Long-term memory loaded from SEC filings since 2019"})
    import yfinance as yf
    px = yf.download(list(T), start="2006-01-01", auto_adjust=True, progress=False)["Close"]  # deep history: events back to 2007
    px["_basket"] = (px[list(T)].pct_change().mean(axis=1).fillna(0) + 1).cumprod()
    desk_memory.fill(px)
    try:
        peers.run()  # related companies' filings (Oklo, NuScale...) as events on our whole basket
    except Exception as e:
        print("peer events failed", e)
    desk_memory.fill(px, archive.EVENTS)
    desk_memory.fill(px, discovery.HISTORY)
    desk_memory.fill(px, discovery.PEOPLE)
    try:  # price action as events (rebuilt each day from prices), outcomes filled the same way
        price_events.build(list(T))
        desk_memory.fill(px, price_events.PATH)
    except Exception as e:
        print("price events failed", e)
    try:  # the discovery engine: test every kind of event on everything collected, every night
        res, new = discovery.run()
        st["discovery"] = {k: res[k] for k in ("run_at", "events", "tests_tonight", "tests_ever")} | {"survivors": len(res["survivors"])}
        for s in new[:3]:
            feed.post("researcher", f"New pattern found by the discovery engine: {s['event']} -> {s['avg_pct']:+.2f}% "
                      f"{discovery.PLAIN.get(s['metric'], s['metric'])} ({s['n']} cases; older half {s['older_avg']:+.2f}%, newer half "
                      f"{s['newer_avg']:+.2f}%; it survived the correction for the {res['tests_tonight']} patterns tested tonight). "
                      "It goes into every stock file and the agents' context.", kind="learn",
                      art={"big": "New pattern found", "sub": s["event"][:60]})
    except Exception as e:
        print("discovery failed", e)
    ev = desk_memory.events()
    st["memory_view"] = {"events": len(ev), "with_outcomes": sum(e.get("r20") is not None for e in ev),
                         "playbooks": desk_memory.all_playbooks(list(T)), "watch": desk_memory.watch_all()[-60:],
                         "recent": [{k: e.get(k) for k in ("date", "ticker", "title", "type", "r0", "r5", "r20")}
                                    for e in sorted(ev, key=lambda e: e["date"])[-40:]]}


# ======================================================================= research lab (evenings + Saturday)
def research_run(st, desk):
    if not CFG.get("research_lab", {}).get("enabled", True) or not desk.available:
        return
    have = sum(1 for t in (st.get("shadow_desk") or {}).get("trades", []) if "ret5d_pct" in t)
    if have < 120:  # practice trades recorded before the lab existed have no market context: replay them once
        try:
            sh = shadow.run_daily(st, rebuild=True)
            feed.post("shadow", f"Rebuilt the practice-trade record with market context for research: {sh.get('new', 0):,} trades.", kind="data")
        except Exception as e:
            feed.post("system", f"Shadow rebuild failed: {e}"[:200]); return
    try:
        res = research_lab.session(st, desk)
    except Exception as e:
        feed.post("system", f"Research session stopped: {e}"[:200]); return
    good = [research_lab._key(h) for h, r in res if r["verdict"] == "promising"]
    if res:
        notify("Research notes", f"Tested {len(res)} idea(s)." + (f" Promising: {', '.join(good)}." if good else " Nothing held up this time.")
               + " Notes are in Team chat.", tags="microscope", who="researcher")


# ======================================================================= huddle: the team talks when something changed
HUDDLE_ROLES = {"level": "Level Analyst: is the support level near the price still clean, or is it about to break?",
                "whale": "Whale Watcher: what do options, short volume and insider activity say right now?",
                "macro": "Macro Analyst: is this a market-wide or sector-wide move, or just this stock?",
                "engineer": "Plant Engineer: what is physically going on at the plants, mines, mills or enrichment behind this "
                            "(outage, refueling, permit, fuel supply, power prices), which company it really affects and for how long?",
                "investigator": "News Investigator: is there news behind this, and is it new or already priced in?",
                "risk": "Risk Manager: argue against whatever the team leans toward if there is a concrete reason.",
                "pm": "Portfolio Manager: close the huddle with one decision."}


def huddle_reasons(st, prices, now, hawk):
    r = []
    r += [f"fast move: {e}" for e in hawk]
    hc = CFG["huddle"]
    for t, c in st["candidates"].items():
        if t in prices and t not in st["armed"] and 0 <= prices[t] / c["entry"] - 1 <= hc["near_entry_pct"] / 100:
            r.append(f"{t} is within {hc['near_entry_pct']}% of its buy zone ${c['entry']} but no order is resting")
    for t in st["armed"]:
        if t in prices and prices[t] / st["armed"][t]["entry"] - 1 <= hc["near_entry_pct"] / 100:
            r.append(f"{t} is about to reach its resting buy at ${st['armed'][t]['entry']}")
    n_tr = len(st["book"]["trades"]) + sum(1 for t in traded(st) if account.lot(st["book"], t, "trade")["qty"] > 1e-6)
    if n_tr != st.get("huddle_trade_count", n_tr):
        r.append("a trade opened or closed since the last huddle")
    st["huddle_trade_count"] = n_tr
    for t, until in (st.get("boss_watch") or {}).items():
        if str(now.date()) <= until and t in prices:
            last_px = st.setdefault("boss_watch_px", {}).get(t)
            if last_px and abs(prices[t] / last_px - 1) >= 0.01:
                r.append(f"{t} (you asked us to watch it) moved {(prices[t] / last_px - 1) * 100:+.1f}% since we last looked")
            st["boss_watch_px"][t] = prices[t]
    hh, mm = map(int, hc["midday"].split(":"))
    if now.time() >= dt.time(hh, mm) and st["flags"].get(f"midday:{now.date()}") is None:
        st["flags"][f"midday:{now.date()}"] = True
        r.append("midday check-in")
    return r


def huddle(st, desk, ex, data, prices, today, brk_state, hawk):
    hc = CFG.get("huddle", {})
    if not (hc.get("enabled") and desk.available and market.market_open()):
        return
    now = market.now_et()
    reasons = huddle_reasons(st, prices, now, hawk)
    if not reasons:
        return
    last = st.get("huddle_last", 0)
    n_today = sum(1 for d in st.get("huddle_log", []) if d == str(today))
    if unleashed():  # as needed: talk about anything NEW; never re-discuss the same thing in the same hour
        seen = st.setdefault("huddle_seen", {})
        reasons = [r for r in reasons if time.time() - seen.get(r, 0) > 3600]
        if not reasons:
            return
        for r in reasons:
            seen[r] = time.time()
        for k in [k for k, v in seen.items() if time.time() - v > 86400]:
            del seen[k]
    else:
        if time.time() - last < hc["min_minutes_between"] * 60 and not any(x.startswith("fast move") for x in reasons):
            return
        if n_today >= hc["max_per_day"]:
            return
    st["huddle_last"] = time.time()
    st.setdefault("huddle_log", []).append(str(today)); del st["huddle_log"][:-50]
    tickers = sorted({t for t in T if any(t in x for x in reasons)}) or list(T)
    snap = {t: {"price": round(prices[t], 2), "waiting_buy": st["candidates"].get(t), "resting_order": st["armed"].get(t),
                "holding": account.lot(st["book"], t, "trade") if account.lot(st["book"], t, "trade")["qty"] > 1e-6 else None,
                "why_no_setup": (st.get("setup_status") or {}).get(t)} for t in tickers if t in prices}
    ctx = {"why_we_are_talking": reasons, "stocks": snap, "sector_pulse": {k: (st.get("sync") or {}).get(k) for k in ("pulse_up", "basket_vs_avg_pct")},
           "nowcast": st.get("nowcast"), "recent_headlines": [f["title"] for f in st["news_feed"] if f["ticker"] in tickers][-8:],
           "plants_now": plant.snapshot(st)}
    order = (["level"] if any("buy" in x for x in reasons) else []) + (["investigator"] if any("fast move" in x for x in reasons) else []) \
        + (["engineer"] if any("fast move" in x or "sector move" in x for x in reasons) else []) + ["macro", "risk"]
    order = list(dict.fromkeys(order))[: max(1, hc["max_turns"] - 1)]
    with feed.thread("Huddle: " + reasons[0][:70], tickers, kind="huddle"):
        feed.say("chief", "Quick huddle. Why: " + "; ".join(reasons) + ".", to="team")
        asked = []
        for role in order:
            try:
                out = desk.ask(role, "fast", HUDDLE_ROLES[role] + " Speak only if you add something; keep it to 1-3 sentences. "
                               "If you need a specific teammate's view, name them in \"ask\". "
                               '{"say":"","to":"","ask":""}', ctx, max_tokens=300)
            except Exception as e:
                feed.say("system", f"{role} couldn't answer: {e}"[:150]); break
            a = feed.norm_who(out.get("ask"))
            if a in HUDDLE_ROLES and a not in order and a != "pm" and len(asked) < 1:
                asked.append(a); order.append(a)
        try:
            d = desk.ask("pm", "fast", HUDDLE_ROLES["pm"] + " Allowed actions only: none; skip (cancel a waiting buy); exit (sell an "
                         "open trade on clear bad news). You can never buy. Default is none. "
                         '{"say":"","to":"team","action":"none|skip|exit","tickers":[],"reason":""}', ctx, max_tokens=300)
        except Exception as e:
            feed.say("system", f"PM couldn't answer: {e}"[:150]); return
        act, tks = str(d.get("action", "none")).lower(), [t for t in (d.get("tickers") or []) if t in T]
        done = []
        for t in tks:
            if act == "skip" and t in st["candidates"]:
                st["candidates"].pop(t); ex_cancel(st, t, "team huddle"); done.append(f"canceled the waiting buy on {t}")
            elif act == "exit" and account.lot(st["book"], t, "trade")["qty"] > 1e-6:
                ex.exit_trade(t, prices[t], "huddle: " + str(d.get("reason", ""))[:100]); done.append(f"sold {t}")
        feed.say("exec", ("Done: " + "; ".join(done)) if done else "No action. Everything stays as it is.", outcome=True, to="team")
    if done:
        notify("Huddle decision", "; ".join(done) + ". " + str(d.get("reason", ""))[:200], tags="speech_balloon", who="pm")


# ======================================================================= pre-market check-in (7:00-9:25 ET)
def premarket(st, desk, prices, today):
    now = market.now_et()
    if now.weekday() >= 5 or market.is_holiday(today) or not (dt.time(7, 0) <= now.time() <= dt.time(9, 25)) or st["flags"].get(f"premarket:{today}"):
        return
    st["flags"][f"premarket:{today}"] = True
    try:
        st["nowcast"] = signals.nowcast(T)
        st["nowcast_date"] = str(today)
    except Exception as e:
        st["nowcast"] = {"error": str(e)[:100]}
    g = [f"{t} {v['expected_gap_pct']:+.1f}%" for t, v in (st.get("nowcast") or {}).items() if isinstance(v, dict) and v.get("expected_gap_pct") is not None]
    heads = [f"{f['ticker']}: {f['title']}" for f in st.get("news_feed", [])[-12:]]
    waiting = {t: c["entry"] for t, c in st["candidates"].items()}
    due = desk_memory.watch_mark(today)
    for x in due:
        feed.post(x.get("by") or "chief", f"Reminder written {x['written']}: {x['what']}", [x["ticker"]] if x.get("ticker") in T else [],
                  kind="alert", art={"big": f"Today: {x['what'][:50]}", "sub": f"Noted by the team on {x['written']}"})
    with feed.thread(f"Pre-market check-in {today:%a %b %d}", T, kind="morning"):
        if due:
            feed.say("chief", "From the memory, due now: " + "; ".join(f"{x['what']} (noted {x['written']})" for x in due), to="team")
        feed.say("chief", f"Morning, team. Market opens at 9:30. Watching {len(T)} stocks; setups waiting on "
                 f"{', '.join(f'{t} at ${p}' for t, p in waiting.items()) or 'none yet'}. Nowcast, what did Asia say?", to="nowcast")
        feed.say("nowcast", ("Asia's close points to these opens: " + ", ".join(g) + ". That gets priced in at 9:30, so it's context, not a trade.")
                 if g else "No fresh Asia close to read yet.", to="chief")
        if desk.available:
            ctx = {"overnight_headlines": heads, "nowcast": st.get("nowcast"), "waiting_setups": st["candidates"],
                   "coming_up_from_memory": desk_memory.watch_due(today, 7),
                   "last_prices": {t: prices.get(t) for t in T}, "research_notebook": research_lab.highlights(st),
                   "local_intel_overnight": intel_brief()}
            try:
                desk.ask("macro", "fast", "Macro Analyst at the pre-market check-in: what matters before the open today (futures mood, "
                         "calendar, overnight sector news)? 2-3 sentences. " '{"say":"","to":""}', ctx, max_tokens=300)
                desk.ask("pm", "fast", "Portfolio Manager closing the pre-market check-in: the plan for the open in 1-2 sentences "
                         "(which waiting setups matter, what would make us cancel one). You can't buy before 9:30. "
                         '{"say":"","to":"team"}', ctx, max_tokens=250)
            except Exception as e:
                feed.say("system", f"Agents unavailable: {e}"[:150])
    feed.post("chief", "Pre-market check-in done: " + (("Asia points to " + ", ".join(g) + ". ") if g else "")
              + (f"Setups waiting on {', '.join(waiting)}." if waiting else "No setups waiting yet.") + " Morning meeting at 9:31.",
              list(waiting), kind="alert", art={"big": "Good morning", "sub": "Pre-market check-in. Open the conversation to see the plan."})


# ======================================================================= panic-day rebound (strategy #2, paper first)
def _dayret(df):
    c = df.Close.dropna()
    return float(c.iloc[-1] / c.iloc[-2] - 1) if len(c) > 2 else 0.0


RELATED_PICKS = set()


def panic_check(st, desk, ex, data, prices, today, brk_state, now, force=False):
    """Market falls 2%+, a stock falls 3%+ and sits 15%+ under its 20-day high: buy near the close, sell 6 sessions later.
    Tested 2019-2026 on 61 such days: +5.3% average over 6 days, up 70% of the time; loses 15-21% when the panic is the
    start of a crash (Mar 2020, May 2022) and stops didn't help, so the protection is position size."""
    cfg = CFG.get("panic_rebound", {})
    if not cfg.get("enabled"):
        return
    book = st["book"]
    late = market.cclock(now) >= dt.time(15, 38)
    for t, lots in list(book["lots"].items()):  # exits: 6 sessions later, near the close (or the first run after)
        L = lots.get("panic") or {}
        if L.get("qty", 0) <= 1e-6 or not L.get("exit_on"):
            continue
        px, avg = prices.get(t, L["cost"] / L["qty"]), L["cost"] / L["qty"]
        if str(today) > L["exit_on"] or (str(today) == L["exit_on"] and late):
            ex.exit_panic(t, px, f"panic-day rebound: held {cfg.get('hold_sessions', 6)} sessions")
        elif late and L.get("opened") != str(today) and px >= avg * (1 + cfg.get("take_profit_pct", 10) / 100):
            ex.exit_panic(t, px, f"panic-day rebound: up {(px / avg - 1) * 100:.1f}%, took the profit early")
        elif late and L.get("opened") != str(today) and t in data and not st["flags"].get(f"missedexit:{t}:{today}"):
            hi = float(data[t].High.iloc[-1]); tp = avg * (1 + cfg.get("take_profit_pct", 10) / 100)
            if hi >= tp > px:
                st["flags"][f"missedexit:{t}:{today}"] = True
                instant_review(st, "missed_exit", f"{t} touched +10% today but closed below, so we didn't sell",
                               {"ticker": t, "bought": round(avg, 2), "high_today": round(hi, 2), "now": round(px, 2), "target": round(tp, 2),
                                "rule": "sell near a close at +10% or on the sell date",
                                "history": "Of 153 past panic trades, 62 touched +10% intraday and closed below; they still finished +10.7% avg, 92% up."},
                               [t])
    for e in st.get("panic_log", []):  # practice record: every trigger is tracked, bought or not
        if e.get("result") is None and str(today) > e["exit_on"] and e["ticker"] in data:
            c = data[e["ticker"]].Close
            px = c[c.index <= pd_ts(e["exit_on"])]
            if len(px):
                e["result"] = round((float(px.iloc[-1]) / e["price"] - 1) * 100, 2)
                if e.get("rule_size_pct") and e.get("size_pct") and e["size_pct"] != e["rule_size_pct"]:  # did the PM's sizing help?
                    sc = st.setdefault("pm_size_score", {"calls": 0, "extra_pct_of_account": 0.0})
                    sc["calls"] += 1
                    sc["extra_pct_of_account"] = round(sc["extra_pct_of_account"] + e["result"] * (e["size_pct"] - e["rule_size_pct"]) / 100, 3)
                    e["pm_size_effect_pct"] = round(e["result"] * (e["size_pct"] - e["rule_size_pct"]) / 100, 3)
                feed.post("researcher", f"Panic-day rebound result: {e['ticker']} picked on {e['date']} at ${e['price']}, "
                          f"{e['result']:+.2f}% after {cfg.get('hold_sessions', 6)} sessions" + (" (we bought it)." if e.get("bought") else " (practice, not bought).")
                          + (f" The PM had said {e['pm_view']}" + (f" ({e['pm_why']})" if e.get("pm_why") else "") + "." if e.get("pm_view") else "")
                          + (f" The PM sized it {e['size_pct']}% instead of the rule's {e['rule_size_pct']}%, which "
                             f"{'added' if e['pm_size_effect_pct'] >= 0 else 'cost'} {abs(e['pm_size_effect_pct']):.2f}% of the account." if e.get("pm_size_effect_pct") is not None else ""),
                          [e["ticker"]], kind="learn")
    held = {t: l["panic"] for t, l in book["lots"].items() if l.get("panic", {}).get("qty", 0) > 1e-6 and l["panic"].get("opened") != str(today)}
    if held and late and not st["flags"].get(f"panic_check:{today}"):
        st["flags"][f"panic_check:{today}"] = True
        rows = {t: {"bought": round(L["cost"] / L["qty"], 2), "now": round(prices.get(t, 0), 2),
                    "pct": round((prices.get(t, 0) / (L["cost"] / L["qty"]) - 1) * 100, 2), "sell_on": L.get("exit_on")} for t, L in held.items()}
        with feed.thread(f"Panic trades check-in {today:%b %d}", list(held), kind="huddle"):
            feed.say("exec", "Where the panic-day trades stand: " + "; ".join(f"{t} {v['pct']:+.1f}% (bought ${v['bought']}, now ${v['now']}, sells {v['sell_on']})"
                     for t, v in rows.items()) + f". Rule: sell at +{cfg.get('take_profit_pct', 10)}% near a close, otherwise on the sell date.", to="team")
            if desk.available:
                ctx = {"panic_trades": rows, "market_today_pct": round(_dayret(data["SPY"]) * 100, 2) if "SPY" in data else None,
                       "recent_headlines": [f"{f['ticker']}: {f['title']}" for f in st.get("news_feed", [])[-12:]], "local_intel": intel_brief(5)}
                try:
                    desk.ask("macro", "fast", "Macro Analyst, daily check on the panic-day rebound trades: is the market calming (rebound "
                             "on track) or is this turning into a real crash? Name what you see. 1-2 sentences. "
                             '{"say":"","to":"team"}', ctx, max_tokens=250)
                    desk.ask("risk", "fast", "Risk Manager, daily check on the panic-day trades: anything that changes the risk (news on one "
                             "stock, the selloff spreading)? The rule sells on the date or at +10%; you can't change it, but say if "
                             "you'd want the owner to know something. 1-2 sentences. "
                             '{"say":"","to":"team"}', ctx, max_tokens=250)
                except Exception as e:
                    feed.say("system", f"Agents unavailable: {e}"[:150])
    if not (force or (dt.time(15, 30) <= market.cclock(now) <= dt.time(15, 58))) or st["flags"].get(f"panic:{today}") or "SPY" not in data:
        return
    st["flags"][f"panic:{today}"] = True
    spy = _dayret(data["SPY"])
    if spy > -cfg.get("market_drop_pct", 2) / 100 and not force:
        return
    hits = []
    for t in T:
        if t not in data or len(data[t]) < 25:
            continue
        r, c = _dayret(data[t]), data[t].Close
        dd = float(c.iloc[-1] / c.iloc[-20:].max() - 1)
        if r <= -cfg.get("stock_drop_pct", 3) / 100 and dd <= -cfg.get("below_high_pct", 15) / 100:
            hits.append((r, dd, t))
    hits.sort()
    rel = cfg.get("related_universe") or []
    if len(hits) < cfg.get("max_names", 3) and rel:  # nuclear first; empty slots go to the related stocks (tested: more trades, same quality)
        try:
            import yfinance as yf
            raw = yf.download(rel, period="4mo", auto_adjust=True, progress=False)
            extra = []
            for t in rel:
                if t in T or t not in raw["Close"]:
                    continue
                c = raw["Close"][t].dropna(); v = raw["Volume"][t].dropna()
                if len(c) < 45 or float(c.iloc[-1]) < 3 or float((c * v).tail(60).mean()) < 20e6:
                    continue
                r_, dd_ = float(c.iloc[-1] / c.iloc[-2] - 1), float(c.iloc[-1] / c.iloc[-20:].max() - 1)
                if r_ <= -cfg.get("stock_drop_pct", 3) / 100 and dd_ <= -cfg.get("below_high_pct", 15) / 100:
                    extra.append((dd_, r_, t, float(c.iloc[-1])))
            for dd_, r_, t, px in sorted(extra)[: cfg.get("max_names", 3) - len(hits)]:
                hits.append((r_, dd_, t)); prices[t] = px
                RELATED_PICKS.add(t)
        except Exception as e:
            print("related panic picks", e)
    if not hits:
        if spy <= -0.02:
            feed.post("chief", f"The market is down {spy * 100:.1f}% today, but none of our stocks is beaten down enough for the panic-day "
                      "rebound (needs -3% today and 15%+ under its 20-day high). No buys.", kind="alert")
        return
    vix = None
    try:
        import yfinance as yf
        vix = float(yf.download("^VIX", period="5d", auto_adjust=True, progress=False)["Close"].dropna().iloc[-1].squeeze())
    except Exception as e:
        print("vix", e)
    steps = cfg.get("size_steps", [10, 15, 25, 40, 50])
    below_trend = False
    try:  # crash brake: research 2026-11-23 (panic_rule_2008): S&P under its 200-day average -> smallest size only
        import yfinance as yf
        sc = yf.download("SPY", period="14mo", auto_adjust=True, progress=False)["Close"].dropna().squeeze()
        below_trend = bool(sc.iloc[-1] < sc.rolling(200).mean().iloc[-1])
    except Exception as e:
        print("spy trend", e)

    def rule_step(r):
        """Tested 2019-2026 (153 trades): calm-market first shocks (VIX under 25) and full capitulation (VIX 40+) rebound best;
        the grinding middle (VIX 25-40) is weakest. Stocks down 8%+ on the day rebound more than ones down 3-5%."""
        s = 0 if vix is None else (1 if (vix < 25 or vix >= 40) else -1)
        s += 1 if r <= -0.08 else (-1 if r > -0.05 else 0)
        if below_trend and cfg.get("small_below_200d", True):
            return 0  # 2008-2018 the rule lost money sizing up into a falling market (-65% drop); smallest size there cut it to -41%
        return max(0, min(len(steps) - 1, 2 + s))
    exit_on = sessions_after(str(today), cfg.get("hold_sessions", 6))
    eq = brk_state["equity"]
    room = max(0.0, eq * cfg.get("max_total_pct", 45) / 100 - sum(l.get("panic", {}).get("qty", 0) * prices.get(t, 0) for t, l in book["lots"].items()))
    cash = spendable(st, today)
    blocked = brk_state.get("no_new_today") and not unleashed()
    bought = []
    with feed.thread(f"Panic day {today:%b %d}: market {spy * 100:+.1f}%", [t for _, _, t in hits], kind="huddle"):
        feed.say("chief", f"Panic day: the market is {spy * 100:+.1f}% and {len(hits)} of our stocks fit the rebound setup: "
                 + ", ".join(f"{t} {r * 100:+.1f}% today, {dd * 100:.0f}% under its high" for r, dd, t in hits)
                 + f". History on 61 days like this: +5.3% average over 6 sessions, up 70% of the time.", to="team")
        views = {}
        if desk.available:
            ctx = {"market_today_pct": round(spy * 100, 2), "vix": vix, "setups": [{"ticker": t, "today_pct": round(r * 100, 2), "under_20d_high_pct": round(dd * 100, 1),
                   "rule_size_pct": steps[rule_step(r)]} for r, dd, t in hits], "rule_picks": [t for _, _, t in hits[: cfg.get("max_names", 3)]],
                   "size_steps_pct": steps, "sp500_below_200_day_average": below_trend,
                   "crash_brake": "When the S&P is under its 200-day average every panic buy is the smallest size (10%). 2008-2018 the rule "
                                  "lost money sizing up into falling markets; this brake turned -2.1%/yr into +1.5%/yr and cut the worst drop from -65% to -41%.",
                   "what_sizes_the_bet": {"VIX under 25": "+7.3% avg, 77% up", "VIX 25-40": "+2-3% avg, 61-66% up (weakest)",
                                          "VIX 40+": "+11.7% avg, 83% up", "stock down 8%+ today": "+7.9%", "stock down 3-5%": "+3.7%"},
                   "history": {"all_61_panic_days_6d_avg_pct": 5.3, "up_share": 0.70, "market_down_3pct_plus_days_avg_pct": 1.9,
                               "market_down_2_to_3pct_days_avg_pct": 7.6, "worst_days": "-15% to -21% (Mar 2020, May 2022)",
                               "sector_only_panics": "no edge"},
                   "recent_headlines": [f"{f['ticker']}: {f['title']}" for f in st.get("news_feed", [])[-15:]], "local_intel": intel_brief(6)}
            try:
                pmv = team_debate(st, desk, "It's a market panic day and the panic-day rebound rule is about to buy the picks near the close. "
                                  "Is this a one-off scare or the start of a crash? Is any pick falling on its OWN bad news? How big should each bet be?",
                                  ctx, "The rules buy the picks (that's what was tested) and set a size for each (rule_size_pct). You decide the "
                                  "final size: keep it, or move it ONE step up or down on size_steps_pct, based on the debate. Your sizing is "
                                  "scored against the rule's. Also say buy or skip as your own view. "
                                  '{"say":"","to":"team","views":[{"ticker":"","view":"buy|skip","size":"up|same|down","why":""}]}',
                                  max_tokens=700)
                views = {v.get("ticker"): v for v in (pmv or {}).get("views") or [] if isinstance(v, dict)}
            except Exception as e:
                feed.say("system", f"Agents unavailable: {e}"[:150])
        feed.say("risk", "The danger is the day this is the start of a crash (March 2020, May 2022: -15% to -21%) and a stop "
                 "won't save us, so size is the protection. Today's sizes follow the conditions"
                 + (f" (VIX {vix:.0f}): " if vix else ": ") +
                 f"between {steps[0]}% and {steps[-1]}% per stock, {cfg.get('max_total_pct', 100)}% total at most. "
                 f"We sell at +{cfg.get('take_profit_pct', 10)}% near a close, or on {exit_on} no matter what.", to="chief")
        for r, dd, t in hits[: cfg.get("max_names", 3)]:
            k = rule_step(r)
            nudge = ((views.get(t) or {}).get("size") or "same").lower()
            k2 = max(0, min(len(steps) - 1, k + (1 if nudge == "up" else -1 if nudge == "down" else 0)))
            if below_trend and cfg.get("small_below_200d", True):
                k2 = 0  # the crash brake isn't up for debate
            dollars = min(eq * steps[k2] / 100, room, cash)
            L = account.lot(book, t, "panic")
            rec = {"date": str(today), "ticker": t, "price": round(prices[t], 2), "day_pct": round(r * 100, 2), "below_high_pct": round(dd * 100, 1),
                   "market_pct": round(spy * 100, 2), "exit_on": exit_on, "result": None, "bought": False,
                   "pm_view": (views.get(t) or {}).get("view"), "pm_why": (views.get(t) or {}).get("why"),
                   "vix": vix, "rule_size_pct": steps[k], "size_pct": steps[k2], "pm_size": nudge}
            if blocked or L["qty"] > 1e-6 or dollars < 5:
                rec["skipped"] = "brakes" if blocked else ("already holding" if L["qty"] > 1e-6 else "no cash left")
            else:
                meta = {"setup": "panic_rebound", "by": "rules", "exit_on": exit_on, "stop": None, "target": None,
                        "why": f"market {spy * 100:+.1f}%, {t} {r * 100:+.1f}% today and {dd * 100:.0f}% under its 20-day high"}
                if ex.buy_market(t, dollars, prices[t], "pr", meta, "panic-day rebound buy near the close"):
                    rec["bought"], rec["dollars"] = True, round(dollars, 2)
                    room -= dollars; cash -= dollars; bought.append(f"{t} ${dollars:.0f}")
            st.setdefault("panic_log", []).append(rec)
        st["panic_log"] = st["panic_log"][-300:]
        feed.say("exec", ("Bought near the close: " + ", ".join(bought) + f". Selling on {exit_on}.") if bought
                 else "No buys placed (" + ", ".join(sorted({x.get("skipped", "") for x in st["panic_log"][-len(hits[: cfg.get("max_names", 3)]):] if x.get("skipped")})) + "); tracked as practice.",
                 to="team", outcome=True)
    feed.post("chief", f"Panic-day rebound: market {spy * 100:+.1f}%. " + (f"Bought {', '.join(bought)}, selling {exit_on}." if bought
              else "Setup found, nothing bought; tracking it as practice."), [t for _, _, t in hits], kind="alert",
              art={"big": f"Panic day: {len(hits)} rebound setup{'s' if len(hits) != 1 else ''}", "sub": f"Market {spy * 100:+.1f}%. Hold 6 sessions"})
    notify("Panic-day rebound", (f"Bought {', '.join(bought)} near the close; selling {exit_on}." if bought else
           f"{len(hits)} setups, nothing bought."), tags="zap")


def instant_review(st, kind, title, facts, tickers=()):
    """Review a mistake the moment it happens: what went wrong, the lesson, and a fix to test. Lessons go into every
    agent's prompt from then on; fixes go to Saturday's research session. Capped per day to keep the cost tiny."""
    desk = DESK.get("d")
    today = str(market.now_et().date())
    n = sum(1 for x in st.get("lessons", []) if x.get("date") == today)
    if not (desk and desk.available) or n >= CFG.get("learning", {}).get("instant_reviews_per_day", 8):
        st.setdefault("lessons", []).append({"date": today, "kind": kind, "title": title, "lesson": None, "facts": facts})
        return
    try:
        with feed.thread(f"Instant review: {title}"[:90], list(tickers), kind="postmortem"):
            out = desk.ask("review", "fast", "Reviewer doing an INSTANT review of something that just went wrong or cost money. "
                           "In plain words: what happened, whether it was bad luck or a bad rule/decision (be honest: one bad "
                           "outcome isn't proof a rule is wrong), the lesson in one sentence the whole team should remember, and "
                           "a fix worth testing on history (or 'none' if it's normal noise). "
                           '{"say":"","to":"team","lesson":"","bad_luck_or_bad_rule":"luck|rule|decision","fix":""}',
                           {"what": kind, "facts": facts, "past_lessons": [x["lesson"] for x in st.get("lessons", []) if x.get("lesson")][-8:]},
                           max_tokens=600)
    except Exception as e:
        print("instant review", e); return
    rec = {"date": today, "kind": kind, "title": title, "lesson": out.get("lesson"), "cause": out.get("bad_luck_or_bad_rule"), "fix": out.get("fix")}
    st.setdefault("lessons", []).append(rec)
    del st["lessons"][:-120]
    fix = str(out.get("fix") or "")
    if fix and fix.lower() not in ("none", "n/a", ""):
        st.setdefault("research_queue", []).append({"q": f"Instant review fix ({kind}): {fix}", "date": today})
    feed.post("review", (out.get("say") or title) + (f"\n\nLesson: {out['lesson']}" if out.get("lesson") else "")
              + (f"\nFix to test Saturday: {fix}" if fix and fix.lower() not in ("none", "n/a") else ""),
              list(tickers), kind="learn", art={"big": title[:60], "sub": "Instant review: the team learns from it right away"})


def watch_mistakes(st, prices, data, today, now):
    """Spot the mistakes as they happen: sold too early, a rule's skipped buy that would have won."""
    keep = []
    for a in st.get("after_sale", []):  # sold too early: the stock ran 5%+ above our exit within 3 sessions
        if sessions_after(a["date"], 3) < str(today) or a["ticker"] not in prices:
            continue
        if not a.get("flagged") and prices[a["ticker"]] >= a["exit"] * 1.05:
            a["flagged"] = True
            instant_review(st, "sold_too_early", f"{a['ticker']} ran {(prices[a['ticker']] / a['exit'] - 1) * 100:+.1f}% after we sold",
                           a, [a["ticker"]])
        keep.append(a)
    st["after_sale"] = keep[-40:]
    keep = []
    for c in st.get("cancels", []):  # a waiting buy the rules canceled: would it have filled and hit its target?
        t = c["ticker"]
        if t not in prices or str(today) > sessions_after(c["valid_until"], 3):
            continue
        px = prices[t]
        if not c.get("would_fill") and px <= c["entry"]:
            c["would_fill"] = str(today)
        if c.get("would_fill") and not c.get("done"):
            if c.get("stop") and px <= c["stop"]:
                c["done"] = "rule saved us"
                st.setdefault("lessons", []).append({"date": str(today), "kind": "rule_saved", "title": f"Skipping {t} avoided a stop-out",
                                                     "lesson": f"The {c.get('why', 'rule')} that canceled {t} avoided a loss.", "facts": c})
            elif c.get("target") and px >= c["target"]:
                c["done"] = "rule cost us"
                instant_review(st, "rule_cost", f"Canceled {t} buy would have hit its target", c, [t])
        keep.append(c)
    st["cancels"] = keep[-40:]


def score_calls(st, prices, today):
    """Every agent prediction ("CCJ up within 5 days") is checked when its time is up; the tally is each agent's track record."""
    tr = st.setdefault("track", {})
    wrong = []
    for c in st.get("calls", []):
        if c.get("result") is not None or c["ticker"] not in prices:
            continue
        if sessions_after(c["date"], c["days"]) > str(today):
            continue
        move = prices[c["ticker"]] / c["price"] - 1
        c["move_pct"] = round(move * 100, 2)
        c["result"] = "right" if (move > 0) == (c["direction"] == "up") and abs(move) > 0.002 else "wrong"
        t = tr.setdefault(c["role"], {"calls": 0, "right": 0, "last": []})
        t["calls"] += 1
        t["right"] += c["result"] == "right"
        t["last"] = (t["last"] + [f"{c['ticker']} {c['direction']} {c['days']}d: {c['move_pct']:+.1f}% ({c['result']})"])[-8:]
        if c["result"] == "wrong":
            wrong.append(c)
    if wrong:
        instant_review(st, "wrong_calls", f"{len(wrong)} wrong prediction{'s' if len(wrong) > 1 else ''} by the team",
                       [{k: c.get(k) for k in ("role", "ticker", "direction", "days", "move_pct", "why")} for c in wrong],
                       sorted({c["ticker"] for c in wrong}))


def mistakes_review(st, desk, today, now):
    """Friday after the close: the team lists the week's mistakes (losses, missed winners, wrong calls, rules that cost money),
    and proposes ONE fix. The fix goes to Saturday's research session to be tested before anything changes."""
    if not (now.weekday() == 4 and now.time() >= dt.time(16, 30)) or st["flags"].get(f"mistakes:{today}") or not desk.available:
        return
    st["flags"][f"mistakes:{today}"] = True
    week = str(today - dt.timedelta(days=7))
    book = st["book"]
    pack = {"closed_trades_this_week": [x for x in book["trades"] if str(x.get("exit_time", "")) >= week],
            "panic_results_this_week": [e for e in st.get("panic_log", []) if e.get("result") is not None and e.get("exit_on", "") >= week],
            "agent_calls_scored_this_week": [c for c in st.get("calls", []) if c.get("result") and c["date"] >= week],
            "track_records": st.get("track"), "why_no_buys": st.get("setup_status"),
            "pm_sizing_score": st.get("pm_size_score"), "conviction_record": conviction_record(st),
            "notes_audit": st.get("notes_audit"), "recent_team_decisions": [c["title"] for c in st.get("chats", [])[-25:]],
            "owner_posts_this_week": [p["text"] for p in st.get("feed", []) if p.get("who") == "owner" and p.get("t", "") >= week]}
    try:
        with feed.thread(f"Mistakes review, week of {today - dt.timedelta(days=4):%b %d}", [], kind="research"):
            out = desk.ask("review", "smart", "Reviewer running the weekly MISTAKES review. Be specific and honest: list this week's "
                           "mistakes (losing trades and why, winners we missed or sold too early/late, agent calls that were wrong, "
                           "rules that cost money, anything the owner had to point out). Put a dollar or % cost on each when you can. "
                           "Then propose exactly ONE fix, written as a testable rule (what to change and what result would prove it). "
                           "It will be tested on history before anything changes. "
                           '{"say":"","to":"team","mistakes":[{"what":"","cost":"","lesson":""}],"fix":{"rule":"","test":""}}',
                           pack, max_tokens=1200)
        fix = (out.get("fix") or {}) if isinstance(out.get("fix"), dict) else {}
        st.setdefault("mistakes_log", []).append({"date": str(today), "mistakes": out.get("mistakes"), "fix": fix})
        del st["mistakes_log"][:-30]
        if fix.get("rule"):
            st.setdefault("research_queue", []).append({"q": f"Mistakes review fix: {fix['rule']} Test: {fix.get('test', '')}", "date": str(today)})
        ms = [m for m in (out.get("mistakes") or []) if isinstance(m, dict)]
        feed.post("review", (out.get("say") or "Weekly mistakes review.") + ("\n\n" + "\n".join(
            f"- {m.get('what')}" + (f" (cost: {m.get('cost')})" if m.get("cost") else "") + (f". Lesson: {m.get('lesson')}" if m.get("lesson") else "")
            for m in ms[:6]) if ms else "") + (f"\n\nProposed fix (tested Saturday before anything changes): {fix['rule']}" if fix.get("rule") else ""),
                  kind="learn", art={"big": "Mistakes review", "sub": f"{len(ms)} mistake{'s' if len(ms) != 1 else ''} found, 1 fix to test"})
    except Exception as e:
        print("mistakes review", e)


def read_results(st, desk, t, f):
    """Read one results release: numbers, guidance, and every dated promise, which goes on the calendar to be checked."""
    with feed.thread(f"{t} results, {f['date']}", [t], kind="news"):
        out = desk.ask("investigator", "fast", "News Investigator reading a company's official RESULTS release (filed with the SEC). "
                       "If this is not actually the quarterly/annual results, set is_results false and stop. Otherwise pull out: the "
                       "key numbers that matter for the stock (production, revenue, profit, cash, contracts), the guidance, and every "
                       "concrete PROMISE management made with a date or deadline (production targets, restarts, licenses, contracts, "
                       "construction milestones), so we can check later if they delivered. Then say in 2 plain sentences what it means "
                       "for the stock. "
                       '{"say":"","to":"team","is_results":true,"numbers":[""],"guidance":[""],'
                       '"promises":[{"promise":"","due":"YYYY-MM-DD (end of the period if only a quarter/year is given)"}],"tone":"better|same|worse"}',
                       {"ticker": t, "form": f["form"], "filed": f["date"], "release_text": f["text"]}, max_tokens=1500)
    if not out.get("is_results", True):
        return
    pr = [p for p in (out.get("promises") or []) if isinstance(p, dict) and p.get("promise")]
    rec = {"ticker": t, "filed": f["date"], "numbers": out.get("numbers"), "guidance": out.get("guidance"), "promises": pr, "tone": out.get("tone"),
           "summary": out.get("say")}
    st.setdefault("results_notes", {}).setdefault(t, []).append(rec)
    st["results_notes"][t] = st["results_notes"][t][-8:]
    desk_memory.watch_add([{"date": p.get("due"), "ticker": t, "what": f"Did {t} deliver? They promised on {f['date']}: {p['promise']}"[:200]}
                           for p in pr], "investigator")
    feed.post("investigator", (out.get("say") or f"{t} reported results.")
              + ("\n\nKey numbers: " + "; ".join(str(x) for x in (out.get("numbers") or [])[:5]) if out.get("numbers") else "")
              + ("\nGuidance: " + "; ".join(str(x) for x in (out.get("guidance") or [])[:3]) if out.get("guidance") else "")
              + ("\nPromises we'll check: " + "; ".join(f"{p['promise']} (by {p.get('due', '?')})" for p in pr[:4]) if pr else ""),
              [t], kind="data", art={"big": f"{t} results", "sub": f"Read from the SEC filing, {f['date']}. {len(pr)} promises tracked"})


def nuclear_weekly(st, desk, prices, today, now, force=False):
    """Friday after the close: the one-page Nuclear Weekly note, published on the site and posted to the feed."""
    if not st["flags"].get("weekly_first") and desk.available:  # the very first issue goes out right away
        st["flags"]["weekly_first"] = True
        force = True
    if not force and (not (now.weekday() == 4 and now.time() >= dt.time(17, 0)) or st["flags"].get(f"weekly:{today}")):
        return
    if not desk.available:
        return
    st["flags"][f"weekly:{today}"] = True
    week = str(today - dt.timedelta(days=7))
    book = st["book"]
    eqs = [e for e in book.get("equity", []) if e[0] >= week]
    pack = {"uranium_price": uprice.summary(), "sprott_trust": sput.summary(), "plants": plant.snapshot(st),
            "big_news_this_week": [f"{p.get('title') or ''} {str(p.get('text') or '')[:220]}" for p in st.get("feed", [])
                                   if p.get("t", "") >= week and p.get("kind") in ("alert", "data", "learn") and p.get("who") not in ("chief",)][-40:],
            "results_this_week": {t: [x for x in v if x["filed"] >= week] for t, v in (st.get("results_notes") or {}).items()},
            "trades_closed": [x for x in book["trades"] if str(x.get("exit_time", "")) >= week],
            "open_positions": {t: {k: round(v.get("qty", 0) * prices.get(t, 0), 2) for k, v in l.items() if v.get("qty", 0) > 1e-6}
                               for t, l in book["lots"].items()},
            "account": {"now": round(account.equity(book, prices), 2), "start": CFG["capital_cap"], "week_start": eqs[0][1] if eqs else None},
            "coming_up": st.get("catalysts", [])[:8], "lessons": [x["lesson"] for x in st.get("lessons", []) if x.get("lesson")][-5:],
            "congress": (st.get("congress_view") or {}).get("latest", [])[:5], "jobs": st.get("jobs_view")}
    out = desk.ask("review", "smart", "Write this week's NUCLEAR WEEKLY: a one-page research note on the nuclear and uranium markets that a "
                   "finance professional would respect. Clear, specific, no hype, plain English, numbers where they matter. Sections: "
                   "'The week in nuclear' (what actually happened and why it matters), 'Uranium and the fuel chain', 'Plants and power', "
                   "'Policy and deals', 'What the desk did' (our trades and why, honest about losses), 'What we're watching next'. "
                   "Give 3-4 headline stats. Only use facts in the data. "
                   '{"headline":"","summary":"2-3 sentences","stats":[{"label":"","value":"","tone":"pos|neg|"}],'
                   '"sections":[{"title":"","paragraphs":[""],"bullets":[""]}]}', pack, max_tokens=3000)
    if not out.get("sections"):
        return
    path = weekly.publish(out, today)
    feed.post("review", f"This week's Nuclear Weekly is out: {out.get('headline', '')}. {out.get('summary', '')}\n\nRead it: {path}",
              [], kind="learn", art={"big": "Nuclear Weekly", "sub": out.get("headline", "")[:80]})


def red_team(st, desk, prices, today, now):
    """Sunday evening: replay the real nuclear/uranium shocks on what we hold, then the Risk Manager plays attacker."""
    if not (now.weekday() == 6 and now.time() >= dt.time(17, 0)) or st["flags"].get(f"redteam:{today}") or not desk.available:
        return
    st["flags"][f"redteam:{today}"] = True
    try:
        s = redteam.stress(st["book"], prices, account.equity(st["book"], prices))
        st["red_team"] = {"date": str(today), **s}
        with feed.thread(f"Nuclear red team, week of {today + dt.timedelta(days=1):%b %d}", list(s["positions"]), kind="research"):
            out = desk.ask("risk", "smart", "Risk Manager playing the NUCLEAR RED TEAM. Your job is to find what could hurt this account "
                           "this week. The account is a nuclear and uranium specialist on purpose, so don't say 'diversify'; find the "
                           "nuclear-specific blowups. Use the replay of real past shocks on today's positions, the catalyst calendar, the "
                           "plants, the uranium price and the Sprott trust. Give the 3 biggest threats (with the dollar damage from the "
                           "closest past shock), the early warning sign for each that the team should watch, and ONE protective idea "
                           "worth testing on history. Plain words. "
                           '{"say":"","to":"team","threats":[{"threat":"","damage":"","warning_sign":""}],"protect_idea":""}',
                           {"stress_test": s, "coming_up": st.get("catalysts", [])[:10], "plants_now": plant.snapshot(st),
                            "sprott": sput.summary()}, max_tokens=1400)
        th = [x for x in (out.get("threats") or []) if isinstance(x, dict)]
        worst = s["scenarios"][0] if s["scenarios"] else None
        if out.get("protect_idea"):
            st.setdefault("research_queue", []).append({"q": f"Red team protection idea: {out['protect_idea']}", "date": str(today)})
        feed.post("risk", (out.get("say") or "Weekly nuclear red team.")
                  + ("\n\n" + "\n".join(f"- {x.get('threat')}" + (f" (damage: {x.get('damage')})" if x.get("damage") else "")
                                          + (f". Watch for: {x.get('warning_sign')}" if x.get("warning_sign") else "") for x in th[:3]) if th else "")
                  + (f"\n\nIdea to test: {out['protect_idea']}" if out.get("protect_idea") else ""),
                  list(s["positions"]), kind="learn",
                  art={"big": "Nuclear red team", "sub": (f"Worst replay: {worst['scenario']}, {'+' if worst['dollars'] >= 0 else '−'}${abs(worst['dollars']):.0f}"
                                                          if worst else "No open positions to stress")})
    except Exception as e:
        print("red team", e)


def park_check(st, ex, prices, today, now):
    """Never let cash sit: near the close, whatever no strategy is using goes into the S&P 500 (SPY).
    Tested 2019-2026 with the panic rule: $1,000 -> $12,120 (37%/yr, worst drop -31%) vs $5,880 leaving it in cash."""
    cfg = CFG.get("parking", {})
    if not cfg.get("enabled") or not (dt.time(15, 52) <= market.cclock(now) <= dt.time(15, 58)) or st["flags"].get(f"park:{today}"):
        return
    st["flags"][f"park:{today}"] = True
    if "SPY" not in prices:
        return
    eq = account.equity(st["book"], prices)
    idle = free_cash(st, today) - eq * cfg.get("keep_cash_pct", 3) / 100
    if idle >= cfg.get("min_usd", 20):
        if ex.buy_market("SPY", idle, prices["SPY"], "pk", {"setup": "parking", "by": "rules"}, f"parked ${idle:.0f} idle cash in the S&P"):
            feed.post("exec", f"Parked ${idle:.0f} of idle cash in the S&P 500 (SPY) so it keeps working overnight. "
                      "It gets sold automatically the moment a trade needs the money.", ["SPY"], kind="alert")


def pd_ts(d):
    import pandas as pd
    return pd.Timestamp(d)


# ======================================================================= discoveries -> action (the bot adjusts itself)
def _rules():
    """Patterns that passed the discovery engine, turned into rules: which event type, which stocks, which way, how long."""
    out = []
    for s in discovery._load(discovery.OUT, {}).get("survivors", []):
        ty, grp = s["event"].split(" (", 1)[0], s["event"].split(" (", 1)[1].rstrip(")")
        tks = (list(T) if grp.startswith("all our") or "basket" in grp else discovery.GROUPS.get(grp, []))
        out.append({"type": ty.replace("intel_", "news_"), "tickers": tks, "basket": "basket" in grp, "up": s["avg_pct"] > 0,
                    "relative": s["metric"].startswith("x") and "basket" not in grp,  # vs the basket: a tilt, not a reason to buy outright
                    "days": {"x1": 1, "x5": 5, "x20": 20, "r1": 1, "r5": 5, "r20": 20}.get(s["metric"], 5), "pattern": s})
    return out


def seasonal_check(st, ex, data, prices, today, now):
    """Two calendar trades that passed their tests (paper):
    - Year-end bounce: around Dec 18 buy the 3 worst year-to-date names (10% each), sell mid-January
      (2007-2025: +13.9% avg, up 15 of 19 years).
    - Uranium spot momentum: after a month where spot uranium rose 5%+, buy the 5 miners (4% each) for 20 sessions
      (miners' next month +6.5% vs +1.7% normally, both halves positive)."""
    if not (dt.time(15, 30) <= market.cclock(now) <= dt.time(15, 58)) or st["flags"].get(f"seasonal:{today}"):
        return
    st["flags"][f"seasonal:{today}"] = True
    book = st["book"]
    eq = account.equity(book, prices)
    bought = []
    if today.month == 12 and today.day >= 18 and not st["flags"].get(f"yearend:{today.year}"):
        st["flags"][f"yearend:{today.year}"] = True
        ytd = {}
        for t in T:
            c = data[t].Close.dropna() if t in data else None
            if c is None or t not in prices:
                continue
            c0 = c[c.index >= f"{today.year}-01-01"]
            if len(c0) > 150:
                ytd[t] = prices[t] / float(c0.iloc[0]) - 1
        for t in sorted(ytd, key=ytd.get)[:3]:
            if account.lot(book, t, "auto")["qty"] > 1e-6:
                continue
            meta = {"setup": "year_end", "by": "rules", "exit_on": f"{today.year + 1}-01-13", "days": "mid-January",
                    "why": f"year-end bounce: {t} is {ytd[t] * 100:+.0f}% this year, among the 3 worst of our stocks"}
            if ex.buy_market(t, eq * 0.10, prices[t], "au", meta, "year-end bounce buy"):
                bought.append(f"{t} ({ytd[t] * 100:+.0f}% this year)")
        if bought:
            feed.post("chief", "Year-end bounce: bought " + ", ".join(bought) + ", 10% each, selling around Jan 13. History (2007-2025): "
                      "the 3 worst names of the year rose 13.9% on average from late December to mid-January, up in 15 of 19 years.",
                      [b.split()[0] for b in bought], kind="alert", art={"big": "Year-end bounce", "sub": "Seasonal trade, sells mid-January"})
    up = uprice.summary() or {}
    sp = dict(up.get("spot") or {})
    mon = sp.get("month")
    dm = sput.spot_momentum()  # daily uranium price from the Sprott trust's books, once a month of history exists
    if dm:
        sp = {"1m_change_pct": dm["change_pct"]}
        mon = f"daily-{dm['as_of'][:7]}"  # at most one trade per calendar month either way
    if mon and (sp.get("1m_change_pct") or 0) >= 5 and not st["flags"].get(f"spotmom:{mon}") and not st["flags"].get(f"spotmom:{(dm or {}).get('as_of', '')[:7]}"):
        st["flags"][f"spotmom:{mon}"] = True
        bought = []
        for t in ("CCJ", "UEC", "DNN", "UUUU", "NXE"):
            if t not in prices or account.lot(book, t, "auto")["qty"] > 1e-6:
                continue
            meta = {"setup": "uranium_momentum", "by": "rules", "exit_on": sessions_after(str(today), 20), "days": 20,
                    "why": f"spot uranium rose {sp['1m_change_pct']:+.1f}% in {mon}; miners have followed strong spot months"}
            if ex.buy_market(t, eq * 0.04, prices[t], "au", meta, "uranium momentum buy"):
                bought.append(t)
        if dm:
            st["flags"][f"spotmom:{dm['as_of'][:7]}"] = True
        if bought:
            st["uranium_momentum"] = {"month": mon, "change": sp["1m_change_pct"], "until": sessions_after(str(today), 20)}
            feed.post("chief", f"Uranium spot rose {sp['1m_change_pct']:+.1f}% in {mon}, so the miners trade is on: bought {', '.join(bought)}, "
                      "4% each, for 20 sessions. After +5% spot months the miners rose 6.5% the next month on average (2007-2026).",
                      bought, kind="alert", art={"big": "Uranium momentum", "sub": f"Spot {sp['1m_change_pct']:+.1f}% last month"})


def auto_check(st, desk, ex, data, prices, today, brk_state, now):
    cfg = CFG.get("auto_trade", {})
    if not cfg.get("enabled"):
        return
    book, late = st["book"], market.cclock(now) >= dt.time(15, 30)
    for t, lots in list(book["lots"].items()):  # exits on the pattern's own horizon
        L = lots.get("auto") or {}
        px = prices.get(t)
        if L.get("qty", 0) > 1e-6 and L.get("setup") == "conviction" and px and market.market_open() and L.get("opened") != str(today):
            if L.get("stop") and px <= L["stop"]:
                ex.exit_panic(t, px, f"conviction trade: stop ${L['stop']} hit", kind="auto", tag="aux"); continue
            if L.get("target") and px >= L["target"]:
                ex.exit_panic(t, px, f"conviction trade: target ${L['target']} hit", kind="auto", tag="aux"); continue
        if L.get("qty", 0) > 1e-6 and L.get("exit_on") and (str(today) > L["exit_on"] or (str(today) == L["exit_on"] and late)):
            ex.exit_panic(t, prices.get(t, L["cost"] / L["qty"]), f"{ {'conviction': 'conviction', 'year_end': 'year-end bounce', 'uranium_momentum': 'uranium momentum'}.get(L.get('setup'), 'discovery') } trade: held {L.get('days', '?')} sessions", kind="auto", tag="aux")
    if not (dt.time(15, 30) <= market.cclock(now) <= dt.time(15, 58)) or st["flags"].get(f"auto:{today}"):
        return
    st["flags"][f"auto:{today}"] = True
    rules = _rules()
    if not rules:
        return
    todays = [e for e in desk_memory.events() + archive._load(archive.EVENTS, []) if e.get("date") == str(today)]
    try:
        todays += price_events.today(data, list(T))
    except Exception as e:
        print("live price events failed", e)
    acted = []
    common = {}
    for e in todays:
        common[e["type"]] = common.get(e["type"], 0) + 1
    for e in todays:
        ty = e["type"].replace("intel_", "news_")
        for ru in [r for r in rules if r["type"] == ty and (e["ticker"] == "_basket") == r["basket"]]:
            targets = (["CCJ"] if ru["basket"] else [e["ticker"]]) if ru["up"] else (list(T) if ru["basket"] else [e["ticker"]])
            targets = [t for t in targets if t in ru["tickers"] and t in T and t in prices]
            p = ru["pattern"]
            for t in targets:
                if ru["up"] and ru["relative"] and common.get(e["type"], 0) > len(T) / 2:
                    continue  # half the group did the same thing today: nothing stands out (that's a market move, not this stock)
                if ru["up"] and ru["relative"]:  # beats its group, not necessarily up: favor it (bigger size on its next support buy)
                    until = sessions_after(str(today), ru["days"])
                    st.setdefault("favor", {})[t] = {"until": until, "mult": cfg.get("favor_mult", 1.5),
                                                     "why": f"{e['title'][:80]} ({p['event']}: {p['avg_pct']:+.2f}% vs the basket)"}
                    acted.append(f"favor {t} until {until}")
                    continue
                if not ru["up"]:
                    until = sessions_after(str(today), ru["days"])
                    st.setdefault("avoid", {})[t] = {"until": until, "why": f"{e['title'][:80]} ({p['event']}: {p['avg_pct']:+.2f}% {discovery.PLAIN.get(p['metric'], '')})"}
                    acted.append(f"no new buys in {t} until {until}")
                    continue
                L = account.lot(book, t, "auto")
                open_n = sum(1 for l in book["lots"].values() if l.get("auto", {}).get("qty", 0) > 1e-6)
                cash = spendable(st, today)
                dollars = min(brk_state["equity"] * cfg.get("size_pct", 10) / 100, cash)
                if L["qty"] > 1e-6 or open_n >= cfg.get("max_open", 3) or dollars < 5 or (brk_state.get("no_new_today") and not unleashed()):
                    continue
                exit_on = sessions_after(str(today), ru["days"])
                meta = {"setup": "discovery", "by": "discovery engine", "exit_on": exit_on, "days": ru["days"],
                        "why": f"{e['title'][:90]} -> {p['event']} averaged {p['avg_pct']:+.2f}% ({p['n']} cases, both halves)"}
                if ex.buy_market(t, dollars, prices[t], "au", meta, "discovery trade"):
                    acted.append(f"bought {t} ${dollars:.0f}, selling {exit_on}")
            st.setdefault("auto_log", []).append({"date": str(today), "event": e["title"][:120], "type": ty, "pattern": p["event"],
                                                  "metric": p["metric"], "avg_pct": p["avg_pct"], "targets": targets, "up": ru["up"]})
    st["auto_log"] = st.get("auto_log", [])[-300:]
    if acted:
        feed.post("researcher", "Acting on what the discovery engine proved: " + "; ".join(acted[:6]) + ". These are patterns that held in "
                  "both halves of the history after correcting for how many were tested.", kind="alert",
                  art={"big": "Discovery in action", "sub": acted[0][:60]})
        notify("Discovery in action", "; ".join(acted[:4]), tags="bulb")


# ======================================================================= intel collector (free, no AI)
def intel_tick(st, today, force=False):
    """Every ~30 min: local + official news by place, tagged by rules. Once a day: every reactor's power level."""
    cfg = CFG.get("intel", {})
    if not cfg.get("enabled", True):
        return
    now = market.now_et()
    if force or time.time() - st.get("intel_at", 0) >= cfg.get("every_minutes", 30) * 60:
        st["intel_at"] = time.time()
        try:
            new = collector.run(tcfg(st), st)
            print(f"intel: {len(new)} new items")
            event_watch(st, new, today)
        except Exception as e:
            print("intel collector failed", e)
        for b in collector.bursts(today):
            key = f"burst:{b['place']}:{today}"
            if st["flags"].get(key):
                continue
            st["flags"][key] = True
            tk = [t for t in b["tickers"] if t in T]
            for t in tk[:3]:
                desk_memory.add_event(t, f"News burst: {b['place']} ({b['today']} stories today vs {b['normal']} normally)", "news_burst", today, "Intel collector")
            feed.post("crowd", f"{b['place']} is suddenly in the news: {b['today']} separate stories today, versus about {b['normal']} on a "
                      "normal day. Something may be happening there; the news desk is reading the stories now.", tk, kind="alert",
                      art={"big": f"{b['place']}: {b['today']} stories today", "sub": f"Normal day: {b['normal']}. Local news collector"})
    if (force or (now.time() >= dt.time(8, 30) and st["flags"].get(f"reactors:{today}") is None
                  and time.time() >= st.get("reactor_retry_at", 0))):
        st["flags"][f"reactors:{today}"] = True
        try:
            if not os.path.exists(reactors.HIST):
                n = reactors.backfill()
                feed.post("researcher", f"Reactor watch is on. Loaded every day of power output since 2019 for the 33 reactors CEG, VST "
                          f"and TLN own, and {n} outages into the long-term memory with what each stock did afterwards. Tested: a single "
                          "outage has not moved CEG (116 cases) and the VST/TLN numbers are too few and too mixed to trade. It stays as context.",
                          ["CEG", "VST", "TLN"], kind="learn", art={"big": f"{n} reactor outages remembered", "sub": "NRC daily power, 2019 to today"})
            snap, new = reactors.run()
            st["reactor_view"] = {"date": snap.get("date"), "us_fleet_running_pct": snap.get("us_fleet_running_pct"), "owners": snap.get("owners")}
            for o in new:
                tk = [o["owner"]] if o["owner"] in T else []
                feed.post("macro", f"Reactor watch: {o['unit']} ({o['owner']}) dropped to low power in today's NRC report. "
                          f"{o['owner']} fleet now {snap['owners'][o['owner']]['fleet_running_pct']}% running. History: one unit going "
                          "offline hasn't moved these stocks on its own; it matters if several go down or a restart drags on.", tk,
                          kind="alert", art={"big": f"{o['unit']} offline", "sub": f"{o['owner']} reactor, NRC daily power report"})
        except Exception as e:
            print("reactor watch failed", e)  # the NRC site blocks some cloud servers: try again in an hour, not tomorrow
            st["flags"].pop(f"reactors:{today}", None)
            st["reactor_retry_at"] = time.time() + 3600
    if (now.time() >= dt.time(8, 35) and st["flags"].get(f"reactors:{today}") and not st["flags"].get(f"plantrep:{today}")
            and DESK.get("d") and DESK["d"].available):  # the Plant Engineer's morning report, once the NRC numbers are in
        st["flags"][f"plantrep:{today}"] = True
        try:
            with feed.thread(f"Plant report {today:%b %d}", ["CEG", "VST", "TLN", "CCJ", "LEU"], kind="research"):
                rep = DESK["d"].ask("engineer", "fast", "Plant Engineer, morning plant report for the team and the owner. From "
                                    "plants_now: which of our companies' reactors are down or back, whether that's routine "
                                    "(refueling season) or a surprise, anything at mines, mills or enrichment, and what it means "
                                    "for which stock today. 3 short plain sentences, no jargon without explaining it. "
                                    '{"say":"","to":"team"}', plant.context(st), max_tokens=500)
            if rep.get("say"):
                feed.post("engineer", rep["say"], ["CEG", "VST", "TLN"], kind="data",
                          art={"big": "Plant report", "sub": f"Reactors, mines and fuel, {today:%b %d}"})
        except Exception as e:
            print("plant report", e)
    if now.time() >= dt.time(17, 30) and not st["flags"].get(f"earnread:{today}") and DESK.get("d") and DESK["d"].available:
        st["flags"][f"earnread:{today}"] = True  # read new results releases; the first run catches up on the last 40 days
        first = not st["flags"].get("earnread_backfill")
        st["flags"]["earnread_backfill"] = True
        done = st.setdefault("earnings_read", [])
        for t in T:
            try:
                fs = earnings.results_filings(t, since_days=40 if first else 5)
            except Exception as e:
                print("earnings", t, e); continue
            for f in fs:
                if f["accession"] in done:
                    continue
                done.append(f["accession"])
                try:
                    read_results(st, DESK["d"], t, f)
                except Exception as e:
                    print("read results", t, e)
        del done[:-200]
    if now.time() >= dt.time(7, 30) and not st["flags"].get(f"weather:{today}"):  # power-market weather, once a day
        st["flags"][f"weather:{today}"] = True
        try:
            wx = weather.forecast()
            st["weather_view"] = wx
            for region, v in wx.items():
                for e in v["extremes"][:1]:
                    key = f"wxalert:{region}:{e['date']}:{e['kind']}"
                    if st["flags"].get(key):
                        continue
                    st["flags"][key] = True
                    note = ("History: PJM heat has been a mild plus for CEG/TLN/VST in the days before (small sample)." if "PJM" in region and e["kind"] == "heat"
                            else "History: Texas extremes have been a minus for VST; extreme cold is the big risk (Winter Storm Uri, 2021, cost Vistra over $1 billion)."
                            if "Texas" in region else "History: PJM cold snaps haven't moved these stocks reliably.")
                    feed.post("engineer", f"Weather watch: {e['kind']} forecast for {region} on {e['date']} (high {e['high_f']}F, low {e['low_f']}F). "
                              f"Stocks exposed: {', '.join(v['stocks'])}. {note}", v["stocks"], kind="data",
                              art={"big": f"{e['kind'].title()} ahead: {region.split(' (')[0]}", "sub": f"{e['date']}, power markets"})
        except Exception as e:
            print("weather", e)
    if not st.get("reactor_view"):  # the page's Plants card: use the last saved reactor report until the next one runs
        try:
            snap = json.load(open(reactors.STATUS))
            st["reactor_view"] = {"date": snap.get("date"), "us_fleet_running_pct": snap.get("us_fleet_running_pct"), "owners": snap.get("owners")}
        except Exception:
            pass
    if not st.get("sput_view"):
        st["sput_view"] = sput.summary()
    st["license_view"] = licenses.summary()
    st["deals_view"] = deals.summary()
    if now.time() >= dt.time(17, 45) and today.weekday() < 5 and not st["flags"].get(f"radarres:{today}"):
        st["flags"][f"radarres:{today}"] = True  # did options into earnings turn out cheap or expensive?
        try:
            for r in radarlog.resolve():
                feed.post("optspec", f"Earnings options check, {r['ticker']}: before earnings the options priced a move of about "
                          f"±{r['implied_move_pct']}% by {r['expiry']}. The stock really moved {r['actual_move_pct']}%"
                          + (f" (earnings day {r['earnings_jump_pct']:+.1f}%)" if r.get("earnings_jump_pct") is not None else "")
                          + f", so the options were {r['options_were']}."
                          + (f" Buying the straddle would have returned {r['straddle_return_pct']:+d}%." if r.get("straddle_return_pct") is not None else ""),
                          [r["ticker"]], kind="data", art={"big": f"Options were {r['options_were']}", "sub": f"{r['ticker']} earnings {r['earnings']}"})
            st["radar_score"] = radarlog.summary()
        except Exception as e:
            print("radar resolve", e)
    if not st["flags"].get(f"catalysts:{today}"):  # the catalyst calendar, refreshed once a day
        st["flags"][f"catalysts:{today}"] = True
        try:
            st["catalysts"] = sorted(catalysts.upcoming(list(T)) + licenses.dated(), key=lambda x: x["date"])
        except Exception as e:
            print("catalysts", e)
    if now.time() >= dt.time(18, 15) and today.weekday() < 5 and not st["flags"].get(f"sput:{today}"):  # Sprott publishes NAV ~6pm
        st["flags"][f"sput:{today}"] = True
        try:
            snap, hist = sput.run()
            s = sput.summary(hist)
            st["sput_view"] = s
            prev = hist[-2]["premium_pct"] if len(hist) > 1 else None
            if s and s.get("premium_pct") is not None:
                crossed = prev is not None and (prev < 0) != (s["premium_pct"] < 0)
                big = s.get("change_1w_pts") is not None and abs(s["change_1w_pts"]) >= 3
                if crossed or big:
                    feed.post("macro", f"Sprott uranium trust: {s['premium_pct']:+.1f}% vs its asset value"
                              + (f" ({s['change_1w_pts']:+.1f} points this week)" if s.get("change_1w_pts") is not None else "") + ". "
                              + ("It's back ABOVE its value, so it can raise money and buy uranium again, which usually supports spot and the miners."
                                 if crossed and s["premium_pct"] >= 0 else
                                 "It slipped below its value, so it can't buy uranium for now." if crossed else
                                 "A big swing in investor demand for uranium."), ["CCJ", "UEC", "NXE", "DNN", "UUUU"], kind="data",
                              art={"big": f"Sprott trust {s['premium_pct']:+.1f}%", "sub": "Premium/discount to the uranium it holds"})
        except Exception as e:
            print("sput", e)
    if now.time() >= dt.time(7, 0) and not st["flags"].get(f"world:{today:%G-W%V}"):  # weekly: the country table
        st["flags"][f"world:{today:%G-W%V}"] = True
        try:
            wsum, changes = world.run()
            for ch in changes[:5]:
                feed.post("macro", f"World watch: {ch['country']} now has {ch['to']:.0f} reactors {ch['what']} (was {ch['from']:.0f}). "
                          "More reactors anywhere means more uranium demand later.", kind="alert",
                          art={"big": f"{ch['country']}: {ch['to']:.0f} {ch['what']}", "sub": "World Nuclear Association table"})
        except Exception as e:
            print("world watch failed", e)
    if now.time() >= dt.time(6, 30) and not st["flags"].get(f"people:{today:%G-W%V}"):  # weekly: bosses, insiders, owners, analysts
        st["flags"][f"people:{today:%G-W%V}"] = True
        try:
            pv, n = people.run(list(T))
            st["people_view"] = pv
            sq = [(t, (people.load(t) or {}).get("short_interest") or {}) for t in pv]
            sq = [(t, s) for t, s in sq if s.get("squeeze_watch")]
            if sq:
                feed.post("whale", "Short squeeze watch (stocks heavily bet against; good news can force short sellers to buy back fast): "
                          + "; ".join((f"{t} {s['pct_of_float']}% of shares sold short, " if s.get("pct_of_float") is not None else f"{t} ") + f"{s.get('days_to_cover') or '?'} days to cover"
                                      + (f" ({s['change_vs_last_month_pct']:+.0f}% vs last month)" if s.get("change_vs_last_month_pct") is not None else "")
                                      for t, s in sq) + ".", [t for t, _ in sq], kind="data",
                          art={"big": "Short squeeze watch", "sub": f"{len(sq)} heavily shorted stock{'s' if len(sq) > 1 else ''}"})
            big = [(t, v["net_insider_usd_12m"]) for t, v in pv.items() if abs(v.get("net_insider_usd_12m") or 0) >= 5_000_000]
            if big:
                feed.post("investigator", "Insider check (bosses trading their own stock, last 12 months): " + "; ".join(
                    f"{t} insiders net {'bought' if v > 0 else 'sold'} ${abs(v) / 1e6:.1f}M" for t, v in big) + ". It's in each stock file.", kind="learn")
        except Exception as e:
            print("people failed", e)
    if now.time() >= dt.time(16, 15) and not st["flags"].get(f"notecheck:{today}"):  # note checker: who reads the stock files
        st["flags"][f"notecheck:{today}"] = True
        rows = notes.report(st)
        if rows:
            NAMES = {"pm": "Portfolio Manager", "macro": "Macro Analyst", "whale": "Whale Watcher", "crowd": "Crowd Reader",
                     "level": "Level Analyst", "investigator": "News Investigator", "risk": "Risk Manager", "scout": "Scout",
                     "review": "Reviewer", "auditor": "Auditor", "strategist": "Strategist", "postmortem": "Postmortem",
                     "technical": "Chart Reader", "researcher": "Researcher"}
            lazy = [NAMES.get(r, r) for r, s, n, _ in rows if s < 0.5]
            feed.post("auditor", "Note check (does each teammate use the stock files?): " + "; ".join(
                f"{NAMES.get(r, r)} used them in {s * 100:.0f}% of {n} answers" + (f" (mostly {', '.join(top[:2])})" if top else "")
                for r, s, n, top in rows) + (f". Not reading enough: {', '.join(lazy)}." if lazy else ". Everyone is using them."), kind="learn")
    if now.time() >= dt.time(7, 0) and not st["flags"].get(f"uprice:{today}"):
        st["flags"][f"uprice:{today}"] = True
        try:
            st["uranium_price"] = uprice.run()
        except Exception as e:
            print("uranium price failed", e)
    if os.environ.get("CONGRESS_API_KEY") and (force or (now.time() >= dt.time(7, 0) and not st["flags"].get(f"congress:{today}"))):
        st["flags"][f"congress:{today}"] = True
        try:
            cs = congress.run()
            st["congress_view"] = cs
            for b in [b for b in (cs or {}).get("latest", []) if b.get("changed")][:3]:
                feed.post("macro", f"Congress: {b['title'][:120]}. Latest: {b['latest_action'][:140]} ({b['action_date']}).", kind="alert")
        except Exception as e:
            print("congress failed", e)
    if now.time() >= dt.time(7, 0) and not st["flags"].get(f"jobs:{today}"):
        st["flags"][f"jobs:{today}"] = True
        try:
            st["jobs_view"] = jobs.run()
        except Exception as e:
            print("jobs tracker failed", e)
    try:
        collector.view(st)
    except Exception as e:
        print("intel view failed", e)
    try:  # page views that don't need a price download: the long-term memory and the research log
        ev = desk_memory.events()
        mv = st.setdefault("memory_view", {})
        mv.update({"events": len(ev), "with_outcomes": sum(e.get("r20") is not None for e in ev), "watch": desk_memory.watch_all()[-60:],
                   "recent": [{k: e.get(k) for k in ("date", "ticker", "title", "type", "r0", "r5", "r20")} for e in sorted(ev, key=lambda e: e["date"])[-40:]]})
        mv.setdefault("playbooks", desk_memory.all_playbooks(list(T)))
        L = json.load(open(os.path.join(ROOT, "research", "trial_ledger.json")))
        st["research_log"] = [{"name": k, "trials": v.get("trials"), "verdict": v.get("verdict")} for k, v in L.get("strategies", {}).items()]
    except Exception as e:
        print("memory/research view failed", e)


def intel_brief(n=8):
    try:
        d = collector.digest(days=3, top=n)
        return {"top_local_items": d["top_items"], "bursts_today": d["bursts_today"], "reactors": d["reactors"]}
    except Exception as e:
        return {"error": str(e)[:100]}


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
        if done_today >= cfg.get("max_per_day", 8) and not unleashed():
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
    dump = "intel collector" in text.lower()
    with feed.thread(f"You asked: {text[:70]}", list(T) + extra, kind="owner"):
        feed.say("owner", text, to="team")
        if dump:
            d = collector.digest(days=7, top=40)
            feed.say("chief", f"The boss sent us everything the collector gathered: {d['stories']} separate stories in 7 days from "
                     f"{len(d['stories_by_place'])} places, plus the reactor report. Everyone read it from your seat. Anything with a date "
                     "goes in the reminders (\"watch\"), and anything worth testing goes to the Research Lab.", to="team")
        feed.say("chief", f"Heard you, boss. Everyone stop and read this. Re-scanning all {len(T)} stocks for a support setup right now."
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
        ans, done = None, []
        if desk.available:
            ctx = {"boss_post": text, "setups_found": found, "why_no_setup": why, "info_only": info, "market_open": is_open,
                   "nowcast": st.get("nowcast"), "prices": {t: prices.get(t) for t in T}, "open_trades": {t: account.lot(st["book"], t, "trade")
                   for t in T if account.lot(st["book"], t, "trade")["qty"] > 1e-6}, "resting_buys": st["armed"],
                   "recent_headlines": [f["title"] for f in st["news_feed"]][-10:], "research_notebook": research_lab.highlights(st)}
            ctx["local_intel"] = collector.digest(days=7, top=40) if dump else intel_brief()
            # everyone hears the boss: each specialist answers from their own seat
            for role, seat in (("macro", "the market and sector mood"), ("whale", "options, short volume and insider moves"),
                               ("crowd", "what retail traders and analysts are saying"), ("risk", "what could go wrong with what the boss wants")):
                try:
                    desk.ask(role, "fast", f"The OWNER (your boss) just posted to the team. Answer him directly from your seat ({seat}): "
                             "what it means for his request and what you'd do. 1-3 plain sentences. Loyal but honest: if what he wants "
                             "would break the rules (buys only at support with a stop), say so and offer the closest thing that doesn't. "
                             '{"say":"","to":"You"}', ctx, max_tokens=260)
                except Exception as e:
                    feed.say("system", f"{role} couldn't answer: {e}"[:150]); break
            try:
                ans = desk.ask("pm", "fast",
                               "Portfolio Manager. The OWNER (your boss) posted; the team has answered. Turn his post into action. "
                               "Allowed actions: cancel_buy (drop a waiting/resting buy), exit (sell an open trade), watch (focus a "
                               "ticker: the team checks it in every meeting for 5 days), research (queue a question for the Research "
                               "Lab), remember (a standing instruction the whole team keeps for 7 days), none. You can never buy "
                               "outside a support setup. Then answer him in plain English: what the team found and exactly what you did. "
                               '{"say":"","to":"You","post":"one-line headline of what the team is doing",'
                               '"actions":[{"type":"cancel_buy|exit|watch|research|remember|none","ticker":"","text":""}]}',
                               ctx, max_tokens=600, to="owner")
            except Exception as e:
                print("owner answer failed", e)
            for a in (ans or {}).get("actions") or []:
                if not isinstance(a, dict):
                    continue
                typ, t, txt = str(a.get("type", "")).lower(), str(a.get("ticker") or "").upper(), str(a.get("text") or "")[:300]
                if typ == "cancel_buy" and t in st["candidates"]:
                    st["candidates"].pop(t); ex_cancel(st, t, "owner/team answer"); done.append(f"canceled the buy on {t}")
                elif typ == "exit" and t in T and account.lot(st["book"], t, "trade")["qty"] > 1e-6:
                    if is_open:
                        ex.exit_trade(t, prices[t], "owner's call: " + txt[:100]); done.append(f"sold {t}")
                    else:
                        account.lot(st["book"], t, "trade")["exit_next_open"] = "owner's call: " + txt[:100]; done.append(f"{t} will be sold at the open")
                elif typ == "watch" and t:
                    st.setdefault("boss_watch", {})[t] = sessions_after(str(today), 5); done.append(f"watching {t} closely for 5 days")
                elif typ == "research" and txt:
                    st.setdefault("research_queue", []).append({"q": txt, "date": str(today)}); done.append("queued a research question")
                elif typ == "remember" and txt:
                    st.setdefault("boss_notes", []).append({"note": txt, "date": str(today)}); del st["boss_notes"][:-20]
                    done.append("the team will keep your instruction in mind for a week")
            if done:
                feed.say("exec", "Done: " + "; ".join(done) + ".", outcome=True, to="owner")
        headline = (ans or {}).get("post") or (f"Found {len(found)} setup{'s' if len(found) != 1 else ''}" if found else "Nothing safe to buy yet")
        feed.post("pm", ((ans or {}).get("say") or "\n".join(lines)) + (("\n\nDone: " + "; ".join(done) + ".") if done else ""),
                  list(found) or T, kind="answer", art={"big": headline[:60], "sub": "The team's answer to your post"})
    notify("Team answered your post", headline, tags="speech_balloon", who="pm")


# ======================================================================= supply-shock and licensing headlines
def event_watch(st, items, today):
    """Big producer cuts (Kazatomprom, Cameco...) and NRC licensing news get their own alert with history attached."""
    import hashlib
    sent = st.setdefault("event_watch", [])
    n_today = sum(1 for e in sent if e.get("date") == str(today))
    for it in items:
        if n_today >= 4:
            break
        text = f"{it.get('title', '')} {it.get('summary', '')}"
        sh, lic = shocks.is_supply_shock(text), licenses.is_license_news(text)
        dl = None if (sh or lic) else deals.is_deal_news(text)
        if not (sh or lic or dl):
            continue
        key = "ev:" + hashlib.sha1((it.get("title") or "")[:80].lower().encode()).hexdigest()[:12]
        if st["flags"].get(key):
            continue
        st["flags"][key] = True
        n_today += 1
        if sh:
            who = shocks.beneficiaries(sh["site"], T)
            h = shocks.HISTORY
            body = (f"Supply shock watch: {it.get('title')}. In the last {h['events']} big producer cuts, the other miners averaged "
                    f"{h['other_miners_5d_avg_pct']:+.1f}% over 5 days and {h['other_miners_20d_avg_pct']:+.1f}% over 20 days, but only "
                    f"{h['up_after_20d']} went up. {h['note']} Watching {', '.join(who)}.")
            kind, tick, title = "supply", who, f"SUPPLY SHOCK? {sh['site'].title()}"
        elif dl:
            who = deals.tickers_for(text) if dl == "deal" else ["LEU", "CCJ"]
            body = (f"Power deal news: {it.get('title')}. {deals.HISTORY}" if dl == "deal" else
                    f"Fuel policy news: {it.get('title')}. The US ban on Russian enriched uranium allows exceptions only until Jan 1 2028; "
                    "Centrus (LEU) gets well over half its supply through 2027 from Russia.")
            kind, tick, title = dl, who, ("POWER DEAL NEWS" if dl == "deal" else "RUSSIAN URANIUM NEWS")
        else:
            who = licenses.tickers_for(text)
            body = f"Licensing news: {it.get('title')}. {licenses.HISTORY}"
            kind, tick, title = "license", who, "NRC LICENSING NEWS"
        rd = ""
        if DESK.get("d") and DESK["d"].available:
            try:
                r = DESK["d"].ask("engineer", "fast", "Plant Engineer: a headline just hit about uranium supply or reactor licensing. In 2 short "
                                  "plain sentences: what physically changes (pounds of uranium, a reactor's timeline) and which of our "
                                  "stocks it really affects. Say plainly if it is minor or already known. "
                                  '{"say":"","to":"team"}', {"headline": it.get("title"), "summary": it.get("summary", "")[:300],
                                                            "history": shocks.HISTORY if sh else (deals.HISTORY if dl else licenses.HISTORY),
                                                            "power_deals_and_fuel_policy": deals.summary() if dl else None,
                                                            "license_tracker": licenses.summary() if lic else None,
                                                            "plants_now": plant.snapshot(st)}, max_tokens=350)
                rd = r.get("say") or ""
            except Exception as e:
                print("event watch engineer", e)
        feed.post("engineer", body + (f"\n\nPlant Engineer: {rd}" if rd else ""), [t for t in tick if t][:4], kind="alert",
                  art={"big": title, "sub": (it.get("title") or "")[:90]})
        notify(title, (it.get("title") or "")[:160] + (f" | {rd[:200]}" if rd else ""), tags="warning" if sh else ("handshake" if dl else "scroll"), priority="high", who="engineer")
        sent.append({"date": str(today), "kind": kind, "title": it.get("title"), "tickers": tick[:4]})
    del sent[:-60]


# ======================================================================= news (agents: veto + exits)
def handle_news(st, desk, ex, data, prices, today, brk_state):
    fresh = news.new_items(tcfg(st), st)
    try:
        ic = CFG.get("intel", {})
        fresh += collector.handoff(st, ic.get("handoff_per_run", 5), ic.get("handoff_min_score", 4.5))
    except Exception as e:
        print("intel handoff failed", e)
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
            try:
                desk_memory.add_event(it["ticker"], it["title"], s.get("event_type"), source=it.get("source", ""),
                                      materiality=s.get("materiality"), direction=s.get("direction"), price=prices[it["ticker"]])
            except Exception as e:
                print("desk memory add failed", e)
    del feed[:-250]
    try:
        event_watch(st, fresh, today)
    except Exception as e:
        print("event watch", e)
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


DEBATE_SEATS = {
    "macro": "Macro Analyst: the market, rates, the sector's trend and what the uranium price and Sprott trust say.",
    "engineer": "Plant Engineer: what is physically going on (plants, mines, enrichment, power prices, weather) and for how long.",
    "investigator": "News Investigator: the facts in the news and filings, what's new vs already known, lawsuits, deals, promises.",
    "whale": "Whale Watcher: options, short interest, insiders, big holders, analysts.",
    "crowd": "Crowd Reader: what retail and chatter are doing, and whether the move is already crowded.",
    "level": "Level Analyst: the chart, support and resistance, how this stock behaves after moves like this.",
    "risk": "Risk Manager: what could go wrong, the worst case in dollars, and whether the size is right.",
}


def team_debate(st, desk, question, ctx, decide_prompt, extra=(), max_tokens=700):
    """The whole team on one decision: every seat gives its view from its own files, then everyone reads everyone else,
    challenges what they disagree with or think was misread, and updates. The Portfolio Manager decides last, having
    heard all of it. Returns the PM's decision (dict in the format decide_prompt asks for)."""
    seats = dict(DEBATE_SEATS)
    for e in extra:
        if e == "optspec":
            seats["optspec"] = "Options Specialist: what the options market prices in, and whether an options trade beats buying the stock."
    feed.say("chief", f"Full-team debate: {question} Everyone gives a view from their own files first, then we argue it out.", to="team")
    first = {}
    for role, seat in seats.items():
        try:
            o = desk.ask(role, "fast", f"{seat} ROUND 1 of a full-team debate on: {question} Give your honest view from your seat, using the "
                         "facts in your desk_notes and the context (name the specific fact). Say for, against or unsure. 2-4 sentences. "
                         '{"say":"","to":"team","stance":"for|against|unsure","key_fact":""}', ctx, max_tokens=450)
            first[role] = {"stance": o.get("stance"), "said": o.get("say"), "key_fact": o.get("key_fact")}
        except Exception as e:
            print("debate r1", role, e)
    second = {}
    for role, seat in seats.items():
        if role not in first:
            continue
        try:
            o = desk.ask(role, "fast", f"{seat} ROUND 2. You've now heard every teammate (round_1). Challenge at least one teammate BY NAME "
                         "where you disagree or think they misread a fact (check it against the files), say what you learned from "
                         "the others, and give your final stance. 2-4 sentences. "
                         '{"say":"","to":"","stance":"for|against|unsure","changed_mind":false}',
                         {**ctx, "round_1": {feed.PEOPLE.get(k, (k,))[0]: v for k, v in first.items()}}, max_tokens=450)
            second[role] = {"stance": o.get("stance"), "said": o.get("say"), "changed_mind": o.get("changed_mind")}
        except Exception as e:
            print("debate r2", role, e)
    tally = {s: sum(1 for v in second.values() if v.get("stance") == s) for s in ("for", "against", "unsure")}
    feed.say("chief", f"Debate done: {tally['for']} for, {tally['against']} against, {tally['unsure']} unsure. Portfolio Manager decides.", to="pm")
    out = desk.ask("pm", "fast", "Portfolio Manager closing a full-team debate. Weigh the arguments, not the headcount: who brought facts, who "
                   "was corrected, what nobody could answer. " + decide_prompt,
                   {**ctx, "round_1": {feed.PEOPLE.get(k, (k,))[0]: v for k, v in first.items()},
                    "round_2": {feed.PEOPLE.get(k, (k,))[0]: v for k, v in second.items()}, "tally": tally}, max_tokens=max_tokens)
    out["_debate"] = {"tally": tally}
    st.setdefault("debates", []).append({"t": feed._now().strftime("%Y-%m-%d %H:%M"), "question": question[:160], "tally": tally,
                                         "decision": {k: v for k, v in out.items() if not str(k).startswith("_")}})
    del st["debates"][:-60]
    return out


ANSWERERS = ("macro", "engineer", "investigator", "whale", "crowd", "level", "risk", "optspec", "researcher")


def mover_radar(st, now):
    """Stocks in the states where big moves (+20% in 10 days) were 5-7x more likely, 2019-2026: very jumpy (volatility
    above 70%/yr) together with a volume surge, a 30%+ drop from the 2-month high, or a 15% move in 5 days. Both
    directions get bigger there. Covers our 10 and the ~74 related stocks; refreshed every 2 hours."""
    m = st.get("movers") or {}
    if m.get("at") and time.time() - m["at"] < 7200:
        return m.get("list", [])
    out = []
    try:
        import yfinance as yf, numpy as np
        names = list(T) + [t for t in CFG.get("panic_rebound", {}).get("related_universe", []) if t not in T]
        raw = yf.download(names, period="4mo", auto_adjust=True, progress=False)
        for t in names:
            try:
                c = raw["Close"][t].dropna(); v = raw["Volume"][t].dropna()
            except Exception:
                continue
            if len(c) < 65 or float(c.iloc[-1]) < 3 or float((c * v).tail(60).mean()) < 20e6:
                continue
            vol = float(c.pct_change().tail(20).std() * np.sqrt(252))
            vr = float(v.iloc[-1] / v.tail(21).iloc[:-1].mean())
            dd = float(c.iloc[-1] / c.tail(60).max() - 1)
            r5 = float(c.iloc[-1] / c.iloc[-6] - 1)
            why = []
            if vol > 0.7:
                if vr >= 3: why.append(f"volume {vr:.1f}x normal")
                if dd <= -0.30: why.append(f"{dd * 100:.0f}% under its 2-month high")
                if abs(r5) >= 0.15: why.append(f"{r5 * 100:+.0f}% in 5 days")
            if why:
                out.append({"ticker": t, "core": t in T, "volatility_pct": round(vol * 100), "why": why, "price": round(float(c.iloc[-1]), 2),
                            "note": "big moves 5-7x more likely here, in either direction"})
    except Exception as e:
        print("mover radar", e)
    out.sort(key=lambda x: (not x["core"], -x["volatility_pct"]))
    st["movers"] = {"at": time.time(), "time": now.strftime("%Y-%m-%d %H:%M"), "list": out[:20]}
    return out[:20]


def questioner(st, desk, prices, now, force=False):
    """The Questioner: every 2 hours it looks at EVERYTHING the bot has seen and asks what nobody noticed, what looks odd,
    what moved without a reason, what got dismissed. Each question goes to the teammate best placed to answer, who must
    say whether it's relevant or not (so 'irrelevant' is a checked answer, not an assumption). Relevant ones become
    research, reminders, or a note to the owner."""
    slot = f"{now:%Y-%m-%d}:{now.hour // 2}"
    if not desk.available or (not force and (not (7 <= now.hour <= 21) or st["flags"].get(f"questioner:{slot}"))):
        return
    st["flags"][f"questioner:{slot}"] = True
    qs = st.setdefault("questions", [])
    pack = {"latest_posts": [f"{p.get('who')}: {(p.get('title') or '')} {str(p.get('text') or '')[:200]}" for p in st.get("feed", [])[-50:]],
            "headlines_seen": [f"{n.get('ticker')}: {n.get('title')}" for n in st.get("news_feed", [])[-40:]],
            "local_intel": intel_brief(12), "prices_now": {t: prices.get(t) for t in T}, "last_closes": st.get("last_prices"),
            "insiders_and_short_interest": {t: {"insiders_net_12m": (people.load(t) or {}).get("insiders_last_12m", {}).get("net_usd"),
                                                "short": (people.load(t) or {}).get("short_interest")} for t in T},
            "sprott": sput.summary(), "uranium": uprice.summary(), "plants": plant.snapshot(st), "coming_up": st.get("catalysts", [])[:10],
            "mover_radar_big_moves_likely": mover_radar(st, now),
            "recent_debates": st.get("debates", [])[-3:], "open_positions": {t: list(l) for t, l in st["book"]["lots"].items()
                                                                            if any(v.get("qty", 0) > 1e-6 for v in l.values())},
            "already_asked": [q["question"] for q in qs[-40:]]}
    try:
        with feed.thread(f"The Questioner, {now:%b %d %H:%M}", [], kind="research"):
            out = desk.ask("questioner", "fast", "You are THE QUESTIONER. Your only job is to notice what the rest of the team hasn't: a stock "
                           "that moved with no explanation, a headline nobody discussed, a number that changed quietly (short interest, "
                           "insiders, the Sprott discount, a reactor), something that contradicts what the team believes, a reminder that "
                           "came due, or something that looks irrelevant but might not be. Ask up to 5 sharp questions, each routed to ONE "
                           f"teammate who can answer it ({', '.join(ANSWERERS)}). Don't repeat already_asked. "
                           '{"say":"","to":"team","questions":[{"question":"","why_it_might_matter":"","ask":"role","kind":"missed|odd|unexplained|maybe_irrelevant"}]}',
                           pack, max_tokens=900)
            for q in [x for x in (out.get("questions") or []) if isinstance(x, dict) and x.get("question")][:5]:
                who = q.get("ask") if q.get("ask") in ANSWERERS else "investigator"
                a = desk.ask(who, "fast", f"The Questioner asks you: {q['question']} (why it might matter: {q.get('why_it_might_matter', '')}). "
                             "Look into it with your files and the context, answer plainly, and give a verdict: relevant (it matters for "
                             "our stocks or trades), irrelevant (checked, and here's why it doesn't), or unsure. Then an action: none, "
                             "watch (with a date), research (a test worth running), or tell_owner. "
                             '{"say":"","to":"The Questioner","verdict":"relevant|irrelevant|unsure","action":"none|watch|research|tell_owner",'
                             '"watch_date":"YYYY-MM-DD","research_test":""}', {**pack, "question": q}, max_tokens=600)
                rec = {"t": now.strftime("%Y-%m-%d %H:%M"), "question": q["question"], "kind": q.get("kind"), "asked": who,
                       "answer": a.get("say"), "verdict": a.get("verdict"), "action": a.get("action")}
                qs.append(rec)
                if a.get("action") == "research" and a.get("research_test"):
                    st.setdefault("research_queue", []).append({"q": f"Questioner: {a['research_test']}", "date": str(now.date())})
                if a.get("action") == "watch" and a.get("watch_date"):
                    desk_memory.watch_add([{"date": a["watch_date"], "ticker": "", "what": f"Questioner follow-up: {q['question']}"[:200]}], "questioner")
                if a.get("action") == "tell_owner":
                    feed.post("questioner", f"Worth your attention: {q['question']}\n\n{feed.PEOPLE.get(who, (who,))[0]}: {a.get('say', '')}", [],
                              kind="alert", art={"big": "Something we almost missed", "sub": "The Questioner"})
        del qs[:-300]
        done = qs[-5:]
        if done:
            feed.post("questioner", "Asked the team: " + " | ".join(f"{q['question']} -> {q.get('verdict') or '?'}" for q in done if q["t"] == now.strftime("%Y-%m-%d %H:%M")),
                      [], kind="learn", art={"big": "The Questioner", "sub": "What nobody had noticed yet, checked"})
    except Exception as e:
        print("questioner", e)


def conviction_record(st):
    """The team's own calls (not a tested rule): how they have done, and how much money that earns them."""
    tr = [x for x in st["book"]["trades"] if x.get("setup") == "conviction"]
    n = len(tr)
    avg = round(sum(x["ret"] for x in tr) / n, 2) if n else None
    mult = 1.0 if n < 5 else max(0.5, min(2.0, 1 + avg / 10))
    return {"closed_trades": n, "avg_return_pct": avg, "wins": sum(1 for x in tr if x["ret"] > 0), "size_multiplier": round(mult, 2)}


def pop_guard(st, t, price, today):
    """No chasing big pops. Nuclear stocks after a +15% one-day jump (1999-2026, 129 cases): median -3.5% (older half)
    and -1.4% (newer half) over the next 5 days, -8.6% / -5.1% over 20 days; both halves agree (research/trial_ledger.json:
    news_pop_fade). Smaller 8-15% pops: the halves disagree, so no rule there."""
    s = [c for _, c in (st.get("spark") or {}).get(t, [])]
    sp = (st.get("spark") or {}).get(t, [])
    if sp and sp[-1][0] != str(today) and price:
        s = s + [price]
    jumps = [s[i] / s[i - 1] - 1 for i in range(max(1, len(s) - 5), len(s)) if s[i - 1]]
    big = max(jumps or [0])
    if big >= 0.15:
        return f"{t} jumped {big * 100:+.0f}% in one day within the last 5 sessions; big pops in our stocks usually give some back (median -3.5% / -1.4% the next week)"
    return None


def conviction_buy(st, ex, prices, today, t, d, headline):
    cfg = CFG.get("conviction", {})
    conv = int(d.get("conviction") or d.get("confidence") or 0)
    if not cfg.get("enabled"):
        return "conviction trades are off"
    if conv < cfg.get("min_conviction", 7):
        return f"BUY wanted but conviction {conv}/10 is under {cfg.get('min_conviction', 7)}"
    if not market.market_open() or t not in prices:
        return "BUY wanted but the market is closed"
    pg = pop_guard(st, t, prices.get(t), today)
    if pg:
        return "BUY wanted but not chasing: " + pg
    book = st["book"]
    if account.lot(book, t, "auto")["qty"] > 1e-6:
        return "already holding a conviction or discovery trade in it"
    eq = book["cash"] + sum(account.lot(book, x, k)["qty"] * prices.get(x, 0) for x in book["lots"] for k in ("trade", "panic", "auto", "core"))
    rec = conviction_record(st)
    open_amt = sum(l.get("auto", {}).get("qty", 0) * prices.get(x, 0) for x, l in book["lots"].items() if l.get("auto", {}).get("setup") == "conviction")
    room = eq * cfg.get("max_total_pct", 60) / 100 * rec["size_multiplier"] - open_amt
    dollars = min(eq * cfg.get("max_pct_each", 30) / 100 * conv / 10 * rec["size_multiplier"], room,
                  spendable(st, today))
    if dollars < 5:
        return "BUY wanted but no cash or room left"
    px = prices[t]
    stop_pct = max(3.0, min(15.0, float(d.get("stop_pct") or 8)))
    tgt_pct = max(3.0, min(40.0, float(d.get("target_pct") or 10)))
    days = max(1, min(cfg.get("max_days", 10), int(d.get("days") or 5)))
    meta = {"setup": "conviction", "by": "agents", "exit_on": sessions_after(str(today), days), "days": days,
            "stop": round(px * (1 - stop_pct / 100), 2), "target": round(px * (1 + tgt_pct / 100), 2), "conviction": conv,
            "why": f"team conviction {conv}/10 on: {headline[:100]}. {str(d.get('reason', ''))[:160]}"}
    if ex.buy_market(t, dollars, px, "au", meta, f"conviction buy {conv}/10"):
        feed.post("pm", f"Conviction buy: {t} ${dollars:.0f} at about ${px:.2f} ({conv}/10). Why: {str(d.get('reason', ''))[:220]} "
                  f"Sell at ${meta['target']} (+{tgt_pct:.0f}%), stop ${meta['stop']} (-{stop_pct:.0f}%), or on {meta['exit_on']}.",
                  [t], kind="alert", art={"big": f"Conviction buy {t}", "sub": f"{conv}/10 from the team. ${dollars:.0f}"})
        notify(f"Conviction buy {t}", f"${dollars:.0f}, {conv}/10. {str(d.get('reason', ''))[:200]}", tags="brain")
        return f"bought ${dollars:.0f} (conviction {conv}/10)"
    return "BUY order failed"


def options_call(st, desk, t, mat, today):
    """A proven bearish event (share offering) on one of our stocks: price the real put and let the Options Specialist decide."""
    if not CFG.get("options_spec", {}).get("enabled", True) or any(p["ticker"] == t and not p.get("closed") for p in st.get("options_book", [])):
        return
    eq = account.equity(st["book"], st.get("last_prices") or {})
    cap, scap = eq * optspec.MAX_PCT / 100, eq * optspec.SPREAD_MAX_PCT / 100
    try:
        moves = optspec.history_moves()
        q = optspec.quote_put(t)
        ev = optspec.evaluate(q, moves)
        sp = optspec.best_spread(t, moves, scap)
    except Exception as e:
        print("options quote", e); return
    if not q or not ev:
        return
    if sp and (ev["avg_return_pct"] <= 0 or q["ask"] * 100 > cap):  # the put doesn't pay or doesn't fit: the spread is the trade
        s, sev = sp
        out = desk.ask("optspec", "fast", "Options Specialist. A possible share offering (dilution) just hit this stock. First: is this "
                       "really the company selling new shares (not a product 'offering' or old news)? A single put is too expensive or "
                       "doesn't pay here, so judge this bear put SPREAD (buy the higher put, sell the lower one; most it can lose is "
                       "what it costs). BUY only if the replay is positive and the news is real. "
                       '{"say":"","to":"team","real_offering":true,"decision":"BUY|SKIP","spreads":1,"why":""}',
                       {"ticker": t, "news": [m.get("title") for m in mat][:5], "spread": s, "replay_of_past_offerings": sev,
                        "single_put_for_comparison": {"put": q, "replay": ev}, "max_dollars": round(scap, 2)}, max_tokens=500)
        n = min(int(out.get("spreads") or 0), int(scap // (s["debit"] * 100)))
        if str(out.get("decision", "")).upper() == "BUY" and out.get("real_offering") and n >= 1:
            fin = team_debate(st, desk, f"The Options Specialist wants a practice put spread on {t} after a share offering ({mat[0].get('title', '')[:100]}). Should we?",
                              {"ticker": t, "spread": s, "replay": sev, "specialist": out}, "Final call: BUY or SKIP the put spread. "
                              '{"say":"","to":"team","decision":"BUY|SKIP","why":""}', extra=("optspec",))
            if str(fin.get("decision", "")).upper() != "BUY":
                feed.post("optspec", f"{t}: the team debated the put spread and said no. {fin.get('why') or fin.get('say') or ''}", [t], kind="data")
                return
            pos = {"kind": "spread", "ticker": t, "long": s["long"], "short": s["short"], "k_long": s["k_long"], "k_short": s["k_short"],
                   "expiry": s["expiry"], "qty": n, "paid": s["debit"], "date": str(today), "exit_on": sessions_after(str(today), 5),
                   "last_bid": s["mid_debit"], "why": str(out.get("why") or "")[:200], "news": mat[0].get("title")}
            st.setdefault("options_book", []).append(pos)
            feed.post("optspec", f"Practice put spread on {t}: buy the ${s['k_long']:g} put, sell the ${s['k_short']:g} put, expiring "
                      f"{s['expiry']}, {n} x ${s['debit']:.2f} (${s['debit'] * 100 * n:.0f}, the most it can lose). Best case "
                      f"+${sev['max_gain_usd'] * n:.0f}. Why: {out.get('why', '')} Replay of {sev['events_replayed']} past offerings: "
                      f"paid off {sev['paid_off_pct']}%, {sev['avg_return_pct']:+.0f}% average. Sells on {pos['exit_on']}, at 2x, or at half.",
                      [t], kind="alert", art={"big": f"Practice put spread: {t}", "sub": "Options Specialist, after a share offering"})
        return
    out = desk.ask("optspec", "fast", "Options Specialist. A possible share offering (dilution) just hit this stock. First: is this really "
                   "the company selling new shares (not a product 'offering' or old news)? Then use the real put price and the replay of "
                   "past offerings to decide: BUY puts only if the replay shows the put paying off on average after the spread, and "
                   "say how many contracts (each = 100 shares; the total must stay under max_dollars). Otherwise SKIP and say why "
                   "(too expensive, wrong kind of news, already priced in). This is a practice book for now: every call is scored. "
                   '{"say":"","to":"team","real_offering":true,"decision":"BUY|SKIP","contracts":1,"why":""}',
                   {"ticker": t, "news": [m.get("title") for m in mat][:5], "put": q, "replay_of_past_offerings": ev,
                    "history": optspec.TRIGGERS["offering_dilution"]["history"], "max_dollars": round(cap, 2)}, max_tokens=500)
    n = int(out.get("contracts") or 0)
    if str(out.get("decision", "")).upper() == "BUY" and out.get("real_offering") and n > 0 and ev["avg_return_pct"] > 0:
        fin = team_debate(st, desk, f"The Options Specialist wants practice puts on {t} after a share offering ({mat[0].get('title', '')[:100]}). Should we?",
                          {"ticker": t, "put": q, "replay": ev, "specialist": out}, "Final call: BUY or SKIP the puts. "
                          '{"say":"","to":"team","decision":"BUY|SKIP","why":""}', extra=("optspec",))
        if str(fin.get("decision", "")).upper() != "BUY":
            feed.post("optspec", f"{t}: the team debated the puts and said no. {fin.get('why') or fin.get('say') or ''}", [t], kind="data")
            return
        n = min(n, int(cap // (q["ask"] * 100)))
        if n < 1:
            feed.post("optspec", f"{t}: a put would make sense but one contract (${q['ask'] * 100:.0f}) is over the {optspec.MAX_PCT}% "
                      "limit for this account. Skipped.", [t], kind="data"); return
        pos = {**q, "qty": n, "paid": q["ask"], "date": str(today), "exit_on": sessions_after(str(today), 5), "last_bid": q["bid"],
               "why": str(out.get("why") or "")[:200], "news": mat[0].get("title")}
        st.setdefault("options_book", []).append(pos)
        feed.post("optspec", f"Practice put on {t}: {n} contract{'s' if n > 1 else ''} of the ${q['strike']:g} put expiring "
                  f"{q['expiry']} at ${q['ask']:.2f} (${q['ask'] * 100 * n:.0f}). Why: {out.get('why', '')} Replay of {ev['events_replayed']} "
                  f"past offerings: paid off {ev['paid_off_pct']}% of the time, {ev['avg_return_pct']:+.0f}% average. Sells on "
                  f"{pos['exit_on']}, at 2x, or if it loses half. Practice book: real prices, no money yet.",
                  [t], kind="alert", art={"big": f"Practice put: {t}", "sub": "Options Specialist, after a share offering"})


def options_mark(st, today, now):
    """Once a day near the close: value each practice put at its real bid; sell at 2x, at half, or on the sell date."""
    if not (market.cclock(now) >= dt.time(15, 45)) or st["flags"].get(f"optmark:{today}"):
        return
    st["flags"][f"optmark:{today}"] = True
    for p in st.get("options_book", []):
        if p.get("closed"):
            continue
        try:
            bid = optspec.mark_spread(p) if p.get("kind") == "spread" else optspec.mark(p["contract"], p["ticker"])
        except Exception as e:
            print("option mark", e); continue
        if bid is None:
            continue
        p["last_bid"] = bid
        why = ("worth 2x what we paid" if bid >= p["paid"] * (1 + optspec.TAKE_PROFIT) else "lost half its value" if bid <= p["paid"] * optspec.CUT_AT
               else "sell date reached" if str(today) >= p["exit_on"] else None)
        if why:
            p["closed"], p["exit_bid"] = str(today), bid
            p["pnl"] = round((bid - p["paid"]) * 100 * p["qty"], 2)
            feed.post("optspec", f"Closed the practice put on {p['ticker']} ({why}): paid ${p['paid']:.2f}, sold at ${bid:.2f}, "
                      f"{'+' if p['pnl'] >= 0 else '−'}${abs(p['pnl']):.2f}.", [p["ticker"]], kind="learn")
            if p["pnl"] < 0:
                instant_review(st, "option_loss", f"Practice put on {p['ticker']} lost ${abs(p['pnl']):.2f}", p, [p["ticker"]])


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
        try:
            entry["engineer"] = desk.ask("engineer", "fast", "Plant Engineer: the team's expert on how nuclear plants, mines, mills, "
                                         "enrichment and power markets physically work. Using how_it_works and plants_now, explain to the "
                                         "traders what this news means in the real world: what actually changes, for which company, how "
                                         "big, and for how long (days, months, years). Say if it's routine (e.g. a planned refueling). "
                                         "2-4 plain sentences. " '{"say":"","to":"team","real_effect":"","lasts":"days|weeks|months|years","routine":false}',
                                         {"ticker": t, "news": material, **plant.context(st)}, max_tokens=500)
        except Exception as e:
            entry["engineer"] = {"error": str(e)[:100]}
        if optspec.is_trigger([m.get("title") or "" for m in mat]) or any(m.get("event_type") == "offering_dilution" for m in mat):
            try:
                options_call(st, desk, t, mat, today)
            except Exception as e:
                print("options call", e)
        sec = [m for m in material if m["source"] == "SEC filing"]
        if sec:
            entry["filings"] = desk.filings(t, sec)
        ctx = {"ticker": t, "held_trade": held, "armed_or_waiting_buy": st["candidates"].get(t),
               "investigator": entry["investigator"], "plant_engineer": entry.get("engineer"), "filings": entry.get("filings"), "chart": ch,
               "short_interest": (people.load(t) or {}).get("short_interest"),
               "short_squeeze_note": "If short interest is high and this news is clearly good and new, short sellers may be forced to buy back fast; that can add to a move (not tested on history yet, use judgment).",
               "desk_memory_playbook": memory.playbook(st, t), "active_theses": active_theses(st, t),
               "similar_past_events": desk_memory.similar(mat[0]["title"], t),
               "what_this_kind_of_event_did_before": desk_memory.playbook(mat[0].get("event_type") or "other", list(T)),
               "rules": "You may SELL an open trade on clearly bad durable news, SKIP to cancel a waiting buy, or BUY a CONVICTION "
                        "trade: your own call from the news plus everything in desk_notes (bosses, insiders, lawsuits, deals, history, "
                        "discoveries). For BUY give conviction 1-10 (7+ needed; it sets the size), target_pct, stop_pct and days (1-10). "
                        "Conviction trades are scored: a good record gives the team more money to bet, a bad one less.",
               "conviction_record": conviction_record(st)}
        entry["pm"] = desk.pm(ctx, "event")
        d = (entry["pm"].get("decisions") or {}).get(t, entry["pm"])
        if held or t in st["candidates"] or str(d.get("action", "")).upper() == "BUY":  # only argue when there is something to act on
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
        ex_cancel(st, t, "team's news call")
        result = "canceled waiting buy"
    elif action == "BUY":
        try:
            fin = team_debate(st, desk, f"Should we make a conviction BUY of {t} on this news: \"{mat[0]['title'][:120]}\"? The PM proposed "
                              f"{d.get('conviction', '?')}/10.", {**ctx, "pm_proposal": d},
                              "Final call on the conviction buy: BUY or HOLD, with conviction 1-10 (7+ to buy), target_pct, stop_pct, days. "
                              '{"say":"","to":"team","action":"BUY|HOLD","conviction":0,"target_pct":10,"stop_pct":8,"days":5,"reason":""}')
            if str(fin.get("action", "")).upper() != "BUY":
                result = f"debate said no ({fin.get('_debate', {}).get('tally')})"
                d = fin
            else:
                d = {**d, **{k: v for k, v in fin.items() if not str(k).startswith("_")}}
                result = conviction_buy(st, ex, prices, today, t, d, mat[0]["title"])
        except Exception as e:
            result = f"debate failed, no buy: {e}"[:120]
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


def fill_check(st, data, today, thr=0.3):
    """Paper limit orders fill the moment the price touches them; real ones often need the price to trade THROUGH.
    Research 2026-11-23 (support buys, Dec 2023-Nov 2026): requiring a 0.3% trade-through cut the average trade from
    +0.44% to +0.15% and the newer half went negative. So every support fill is checked against the day's real low/high
    and the honest record (touch-only fills removed) is kept next to the paper one."""
    book = st["book"]

    def bar(t):
        d = data.get(t)
        if d is None or not len(d) or d.index[-1].date() != today:
            return None
        return float(d.Low.iloc[-1]), float(d.High.iloc[-1])
    for t, lots in book["lots"].items():
        L = lots.get("trade") or {}
        if L.get("qty", 0) > 1e-6 and L.get("opened") == str(today) and not L.get("fill_quality"):
            b = bar(t)
            if b:
                L["fill_quality"] = "touch-only" if b[0] >= L["entry"] * (1 - thr / 100) else "traded through"
    for r in book["trades"]:
        if r.get("setup") == "patient_level":
            if str(r.get("exit_time") or "")[:10] == str(today) and r.get("why_out") == "target hit" and not r.get("exit_fill"):
                b = bar(r["ticker"])
                if b:
                    r["exit_fill"] = "touch-only" if b[1] <= r["exit"] * (1 + thr / 100) else "traded through"
    sup = [r for r in book["trades"] if r.get("entry_fill") or r.get("exit_fill")]
    honest = [r for r in sup if r.get("entry_fill") != "touch-only"]
    adj = lambda r: (r.get("realistic_pnl", r["pnl"]) if r.get("exit_fill") != "touch-only" else
                     round((r.get("realistic_pnl", r["pnl"])) - r["dollars"] * 0.5 / 100, 2))  # a missed target usually means a worse exit
    st["fill_honesty"] = {"checked_trades": len(sup), "touch_only_entries": sum(1 for r in sup if r.get("entry_fill") == "touch-only"),
                          "touch_only_exits": sum(1 for r in sup if r.get("exit_fill") == "touch-only"),
                          "paper_pnl": round(sum(r["pnl"] for r in sup), 2), "honest_pnl": round(sum(adj(r) for r in honest), 2),
                          "note": "Honest = drop trades whose buy only touched the price, charge real costs, and take 0.5% off target exits that only touched."}
    return st["fill_honesty"]


def review(st, desk, data, prices, today, brk_state):
    # Friday's weekly pieces (strategist, auditor, drift check, practice-trade lessons). If a Friday was missed, the next review catches up.
    lw = st["flags"].get("weekly_review_done")
    is_weekly = today.weekday() == 4 or not lw or lw < str(today - dt.timedelta(days=7))
    if is_weekly:
        st["flags"]["weekly_review_done"] = str(today)
    try:
        fh = fill_check(st, data, today)
        if fh.get("checked_trades"):
            feed.post("officer", f"Honest fills check: of {fh['checked_trades']} support trades, {fh['touch_only_entries']} buys and "
                      f"{fh['touch_only_exits']} target sells only touched the price (a real order might not have filled). "
                      f"Paper P&L ${fh['paper_pnl']:+.2f}; honest P&L ${fh['honest_pnl']:+.2f}.", [], kind="data",
                      art={"big": f"Honest P&L ${fh['honest_pnl']:+.2f}", "sub": f"Paper says ${fh['paper_pnl']:+.2f}"})
    except Exception as e:
        print("fill check", e)
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
    try:
        memory_daily(st, data)
    except Exception as e:
        print("desk memory daily failed", e)
    if CFG.get("research_lab", {}).get("daily", True):
        research_run(st, desk)
    if is_weekly:
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
    if is_weekly:  # feedback loop: is each live signal still behaving like its research said?
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
    with feed.thread(f"Daily review {today:%a %b %d}" + (" + weekly strategy" if is_weekly else ""), T, kind="review"):
        closed = [x for x in book["trades"] if str(x.get("exit_time", "")).startswith(str(today))]
        feed.say("officer", f"Numbers for the reviewer: account ${eq:,.2f} vs ${CFG['capital_cap']:,.0f} start, "
                 f"{brk_state['week_pct']:+.2f}% this week; the S&P buy-and-hold would be at ${bh:,.2f}. "
                 f"{len(closed)} trade(s) closed today. Settled cash ${officer['settled_cash']:,.2f}.")
        rev = None
        if desk.available:
            try:
                rev = desk.reviewer(packet, weekly=is_weekly)
                if is_weekly:
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
    for t in tick + ["SPY"]:  # a ticker Yahoo failed to send keeps its last known price
        if t not in prices and (st.get("last_prices") or {}).get(t):
            prices[t] = st["last_prices"][t]
    st["last_prices"], st["last_cycle"] = {t: round(prices[t], 2) for t in tick + ["SPY"] if t in prices}, now.strftime("%Y-%m-%d %H:%M ET")
    try:  # last 30 daily closes per stock, for the trade hover cards on the page
        st["spark"] = {t: [[str(i.date()), round(float(c), 2)] for i, c in data[t].Close.dropna().tail(30).items()] for t in tick if t in data}
    except Exception as e:
        print("spark", e)
    book = st["book"]
    is_open = market.market_open() or "close" in force or "morning" in force
    if is_open:
        process_fills(st, br, ex, today)
    brk_state = account.brakes(book, prices, CFG, today)
    if unleashed() and (brk_state.get("killed") or brk_state.get("risk_mult", 1) < 1):
        # paper keeps learning through a bad stretch; the drop still counts against the promotion gate
        if brk_state.get("killed"):
            notify_once(st, "paper_kill", "Paper account down 20%+",
                        "On real money this would stop all trading. On paper it keeps going so the team keeps learning; "
                        "the drop still counts against the promotion gate.")
        brk_state["killed"], brk_state["risk_mult"] = False, 1.0
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
    try:  # weekly reviews run after the close / on the weekend, so they sit outside the market-hours block
        questioner(st, desk, prices, now)
        mistakes_review(st, desk, today, now)
        nuclear_weekly(st, desk, prices, today, now)
        red_team(st, desk, prices, today, now)
    except Exception as e:
        traceback.print_exc()
    if is_open:
        if (st["flags"].get("morning_done") != str(today) and now.time() >= dt.time(9, 31)) or "morning" in force:
            if now.time() >= dt.time(9, 31) and market.market_open():  # a forced test meeting before the open must not use up the real one
                st["flags"]["morning_done"] = str(today)
            morning(st, desk, br, ex, data, prices, today, brk_state)
            process_fills(st, br, ex, today)
        manage_open(st, ex, prices, today, brk_state)
        process_fills(st, br, ex, today)
        try:
            panic_check(st, desk, ex, data, prices, today, brk_state, now, force="panic" in force)
            auto_check(st, desk, ex, data, prices, today, brk_state, now)
            seasonal_check(st, ex, data, prices, today, now)
            process_fills(st, br, ex, today)
            park_check(st, ex, prices, today, now)
            process_fills(st, br, ex, today)
            options_mark(st, today, now)
            score_calls(st, prices, today)
            watch_mistakes(st, prices, data, today, now)
        except Exception as e:
            traceback.print_exc()
        try:
            refresh_candidates(st, desk, data, prices, today, brk_state)
            arm(st, ex, prices, today, brk_state)
            process_fills(st, br, ex, today)
        except Exception as e:
            traceback.print_exc()
    try:
        premarket(st, desk, prices, today)
    except Exception as e:
        print("premarket failed", e)
    if (now.weekday() < 5 and dt.time(9, 0) <= now.time() < dt.time(9, 29) and not market.is_holiday(today)
            and (st.get("morning") or {}).get("date") != str(today)):
        try:  # the full morning meeting, before the bell
            st["morning"] = {"date": str(today), "prepped": False}
            morning_prep(st, desk, data, prices, today, brk_state)
        except Exception as e:
            traceback.print_exc()
    intel_tick(st, today, force="intel" in force)
    try:  # did every scheduled job run? (alerts + one automatic retry)
        watchdog.check(st, now, market.cclock, market.is_holiday,
                       lambda title, body: notify(title, body, tags="rotating_light", priority="high", who="watchdog"),
                       lambda msg: feed.post("watchdog", msg, [], kind="alert", art={"big": "Missed job", "sub": msg[:90]}))
    except Exception as e:
        print("watchdog", e)
    if time.time() - st.get("dossier_at", 0) >= 1800 or "intel" in force:
        st["dossier_at"] = time.time()
        try:
            dossier.build_all(st, data, list(T))
        except Exception as e:
            print("stock files failed", e)
    hawk = hawk_events(st)
    try:
        huddle(st, desk, ex, data, prices, today, brk_state, hawk)
    except Exception as e:
        print("huddle failed", e)
    handle_owner_posts(st, desk, ex, data, prices, today, brk_state)
    handle_news(st, desk, ex, data, prices, today, brk_state)
    if ((now.weekday() < 5 and dt.time(15, 40) <= market.cclock(now) <= dt.time(15, 58)) or "close" in force) \
            and st["flags"].get("close_done") != str(today):
        st["flags"]["close_done"] = str(today)
        close_routine(st, desk, ex, data, prices, today, brk_state)
        process_fills(st, br, ex, today)
    if ((now.weekday() < 5 and dt.time(16, 5) <= now.time() <= dt.time(19, 0)) or "review" in force) \
            and st["flags"].get("review_done") != str(today):
        if now.weekday() < 5 and dt.time(16, 5) <= now.time() <= dt.time(19, 0):  # a forced test review must not use up the real one
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
        if time.time() - st.get("online_at", 0) > 6 * 3600:  # restarts after code updates happen often: announce only real starts
            notify("Swing Desk online", f"Always-on mode started ({br.name}). Hawk mode: live prices, news every minute.", tags="green_heart")
        st["online_at"] = time.time()
        last_cycle = 0
        while True:
            now = market.now_et()
            weekday = now.weekday() < 5
            active = weekday and dt.time(8, 0) <= now.time() <= dt.time(19, 0)  # every minute while it matters
            # off-hours it still wakes: overnight news, your posts, the collector (every 10 min weeknights, 30 min weekends)
            due = active or time.time() - last_cycle >= (600 if weekday else 1800)
            if not due:  # your posts never wait: check the inbox every minute, day or night, and run at once if you wrote
                try:
                    due = any(m["id"] not in st.get("inbox_seen", []) for m in inbox.poll("2h"))
                except Exception:
                    pass
            if due:
                last_cycle = time.time()
                try:
                    if now.weekday() == 5 and now.time() >= dt.time(10, 0) and not st["flags"].get(f"research:{now:%F}"):
                        st["flags"][f"research:{now:%F}"] = True  # Saturday research session (was the GitHub 10am run)
                        T[:] = st.get("active") or CFG["tickers"]
                        try:
                            memory_daily(st)
                        except Exception as e:
                            print("desk memory failed", e)
                        research_run(st, desk)
                    else:
                        cycle(st, desk, br, ex)
                    if not active and not archive.complete():  # nights and weekends: read old news, 4 minutes at a time
                        prog = archive.step(240)
                        st["archive_progress"] = prog
                        if prog.get("topics_done") == prog.get("topics") and not st["flags"].get("archive_done"):
                            st["flags"]["archive_done"] = True
                            feed.post("researcher", f"The news archive is complete: {prog['events_total']:,} tagged events since 2019 across "
                                      "our 10 companies, the uranium market, government and laws. The discovery engine tests them every night.", kind="learn")
                except Exception as e:
                    traceback.print_exc()
                    notify_once(st, "cycle_error", "Desk cycle error", str(e)[:250])
                st["heartbeat"] = now.strftime("%Y-%m-%d %H:%M")
                save_state(st)
                if time.time() - last_dash > 300:
                    dashboard.build(st, CFG); last_dash = time.time()
                # save to GitHub so the page updates: every 15 min in market hours, hourly otherwise (keeps data use low)
                fresh = len(st.get("feed", [])) + sum(len(c.get("msgs", [])) for c in st.get("chats", [])[-5:])
                news = fresh != st.get("_pushed_feed")  # something new to see (your post answered, a trade, an alert): save now
                if news or time.time() - last_dash > 300:
                    dashboard.build(st, CFG); last_dash = time.time()
                if os.environ.get("AUTO_GIT") == "1" and (time.time() - last_push > (600 if active else 3600) or (news and time.time() - last_push > 45)):
                    st["_pushed_feed"] = fresh
                    before = os.popen(f"git -C {ROOT} rev-parse HEAD").read().strip()
                    rc = os.system(f"cd {ROOT} && for p in state.json docs orders data memory research/trial_ledger.json research/discoveries.json; do [ -e \"$p\" ] && git add -A \"$p\"; done; "
                                   f"git commit -qm 'desk {now:%F %H:%M}' >/dev/null 2>&1; git pull -q --rebase --autostash -X theirs >/dev/null 2>&1; git push -q")
                    if rc:
                        notify_once(st, "git_push", "Desk can't save to GitHub", "The page won't update until the VM can push (check the deploy key).")
                    last_push = time.time()
                    changed = os.popen(f"git -C {ROOT} diff --name-only {before} HEAD -- '*.py' config.json requirements.txt deploy").read().strip()
                    if before and changed:  # new code arrived: restart so it runs (systemd brings the bot straight back)
                        print("new code:", changed.replace("\n", ", "))
                        save_state(st)
                        sys.exit(0)
            wake.wait(CFG.get("daemon_poll_seconds", 60) if active else 60)
            wake.clear()
    elif args[0] == "research":
        T[:] = st.get("active") or CFG["tickers"]
        try:
            memory_daily(st)
        except Exception as e:
            print("desk memory failed", e)
        research_run(st, desk)
    elif args[0] == "intel":
        T[:] = st.get("active") or CFG["tickers"]
        intel_tick(st, market.now_et().date(), force=True)
        v = st.get("intel_view") or {}
        print(v.get("week"), "stories this week;", "failed sources:", (v.get("health") or {}).get("failed"))
        cv = st.get("congress_view")
        print("congress key:", "set" if os.environ.get("CONGRESS_API_KEY") else "MISSING",
              "| bills tracked:", (cv or {}).get("tracked"), "|", [b["title"][:70] for b in (cv or {}).get("latest", [])[:3]])
    elif args[0] == "test-notify":
        t = ntfy_topic()
        if not t:
            print("NTFY_TOPIC secret is empty or missing."); sys.exit(1)
        print(f"Sending to topic: {t[:3]}{'*' * max(len(t) - 3, 0)} ({len(t)} characters)")
        notify("Swing Desk connected", "Phone alerts work: lineup, armed orders, fills, news, morning brief, daily review.")
        if NOTIFY_ERR:
            e_ = NOTIFY_ERR[-1]
            print("Sending failed:", e_)
            if "429" in e_:
                print("ntfy.sh's free limit for this shared GitHub machine is used up. Fix: make a free ntfy.sh account, "
                      "create an access token, and add it as the GitHub secret NTFY_TOKEN.")
            sys.exit(1)
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
