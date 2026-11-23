"""The Claude agent desk: 15 roles. 12 are Claude calls, 3 are plain code (marked CODE).

INTELLIGENCE
  1  News Scout (fast)        scores every new headline 0-10 and tags it new / follow-up / stale
  2  Investigator (smart+web) digs into material news: new or priced in? durable? good or bad?
  3  Filings Analyst (fast)   reads SEC filings: earnings, share sales (dilution), insiders, contracts
  4  Whale Watcher (fast)     options walls, unusual options, skew, short volume, insider buying
  5  Macro & Sector (fast)    market health, VIX, futures, peers overnight, holidays, Fed, earnings
  6  Crowd Analyst (fast)     Reddit buzz, analyst consensus: flags "don't chase" situations
STRATEGY
  7  Technical Analyst (fast) trend / entry quality for a specific decision
  8  Level Trader (fast)      reviews today's support-level setups: arm or skip (can't loosen rules)
  9  Core Manager (fast)      weekly note on the long-term holdings
DECISION & EXECUTION
  10 Risk Manager (fast)      vetoes and shrinks; knows brakes, earnings, concentration
  11 Portfolio Manager (smart) final call on every trade
  12 Execution Trader         CODE (run.py/broker.py): penny-exact limit prices, fractional qty, stops
  13 Account Officer          CODE (account.py): settled cash, wash sales, tax estimate, brakes
REVIEW & LEARNING
  14 Daily Reviewer (smart)   end-of-day report
  15 Performance Auditor (smart) weekly grades: which setups, signals and vetoes actually made money
  16 Post-mortem Analyst (fast) after EVERY closed trade: why it won/lost, and is there a lesson?
  17 Strategist (smart+web)   weekly: connects tariffs, wars, policy and supply news to the three stocks using
                              the desk's own memory; writes testable theses (and flags option ideas to the owner)

Research basis: LLMs add value extracting/judging information; live AI-trading contests mostly lost
money when models also sized and executed. So agents advise, code enforces.
Set DESK_MOCK=1 to run with fake answers (no key, no cost).
"""
import json, os, re, datetime as dt
import feed

MOCK = os.environ.get("DESK_MOCK") == "1"
feed.PRACTICE = MOCK

HOUSE = ("You work on a small, long-only trading desk ($1,000-scale account, no margin, no options trading yet) that runs ONE "
         "simple strategy, Patient Levels: a resting limit buy just above a support level, left for up to 5 sessions, "
         "sold at the next resistance, at the stop just under the zone, or after 3 days. The desk trades a fixed lineup, the "
         "nuclear fuel chain, at most 3 trades at a time: miners CCJ (Cameco), NXE (NexGen), UEC (Uranium Energy), DNN (Denison), "
         "UUUU (Energy Fuels); enricher LEU (Centrus); reactor parts and fuel BWXT; nuclear plant operators CEG (Constellation), "
         "VST (Vistra), TLN (Talen). No new buys while the whole basket is falling (below its 10-day average). The owner's thesis is that AI data centers will need nuclear power. Be skeptical and concrete; "
         "most news and signals are noise. Facts the desk's research established: public news is priced in within "
         "seconds-minutes, so speed is not our edge; Asia's close predicts the opening gap but nothing after the open; "
         "moves on stale/recycled news tend to reverse within a week; drift after BAD news is more reliable than after good "
         "news; retail-buzz spikes tend to reverse over 1-4 weeks; open-market insider BUYS are meaningful, planned (10b5-1) "
         "sales are not; big open-interest strikes are not proven multi-day support. "
         "You are part of a team that talks in a group chat the owner reads. Every JSON reply MUST include a key \"say\": "
         "1-3 plain-English sentences, first person, to your teammates, explaining your reasoning so a beginner could follow "
         "(no jargon without a short explanation). If 'teammates_said' is in your input, name the teammate you agree or "
         "disagree with and why. Also include \"to\": the one teammate you are mainly answering (their job title, e.g. \"Risk Manager\"), "
         "or \"team\" if no one in particular. If you learn of a FUTURE dated event that could move our stocks (a regulator "
         "decision, a contract award date, guidance, a vote, an auction), add \"watch\": [{\"date\":\"YYYY-MM-DD\",\"ticker\":\"\",\"what\":\"\"}] "
         "so the desk remembers it for months. Reply with JSON only, no prose outside JSON.")


class Budget(Exception):
    pass


class Desk:
    def __init__(self, cfg, state):
        self.cfg, self.state = cfg, state
        self.spend = state.setdefault("spend", {"day": "", "day_usd": 0.0, "month": "", "month_usd": 0.0, "total_usd": 0.0,
                                                "by_role": {}})
        self.spend.setdefault("by_role", {})
        self.client = None
        if not MOCK and os.environ.get("ANTHROPIC_API_KEY"):
            import anthropic
            self.client = anthropic.Anthropic()
        self.log = state.setdefault("desk_log", [])

    @property
    def available(self):
        return self.cfg["agents_enabled"] and (MOCK or self.client is not None)

    # ---------------- plumbing
    def _check_budget(self):
        today, month = str(dt.date.today()), str(dt.date.today())[:7]
        if self.spend["day"] != today:
            self.spend["day"], self.spend["day_usd"] = today, 0.0
        if self.spend["month"] != month:
            self.spend["month"], self.spend["month_usd"] = month, 0.0
        day_cap = self.cfg.get("budget_daily_usd")
        total_cap = self.cfg.get("budget_total_usd")  # matches the prepaid credit: stop before the balance hits zero
        if total_cap is not None and self.spend.get("total_usd", 0) >= total_cap:
            raise Budget(f"Agent budget reached: ${self.spend.get('total_usd', 0):.2f} of the ${total_cap:.2f} credit used. Add credit and raise budget_total_usd.")
        if (day_cap is not None and self.spend["day_usd"] >= day_cap) or self.spend["month_usd"] >= self.cfg["budget_monthly_usd"]:
            raise Budget(f"Agent budget reached (today ${self.spend['day_usd']:.2f}, month ${self.spend['month_usd']:.2f})")

    def _charge(self, role, model, usage, searches=0):
        pin, pout = self.cfg["price_per_mtok"].get(model, [3, 15])
        cost = usage.input_tokens / 1e6 * pin + usage.output_tokens / 1e6 * pout + searches * self.cfg["web_search_per_call"]
        for k in ("day_usd", "month_usd", "total_usd"):
            self.spend[k] = round(self.spend[k] + cost, 5)
        self.spend["by_role"][role] = round(self.spend["by_role"].get(role, 0) + cost, 5)
        return cost

    def ask(self, role, tier, system, payload, web_search=0, max_tokens=900, to=None):
        notes = [n for n in self.state.get("boss_notes", []) if n.get("date", "") >= str(dt.date.today() - dt.timedelta(days=7))]
        if notes and isinstance(payload, dict):
            payload = {**payload, "owner_standing_instructions": [n["note"] for n in notes][-5:]}
        import notes
        system, payload = notes.attach(role, system, payload)
        system += (' Always also add "why": 1-2 plain sentences on the reasoning behind your message (what you checked and '
                   'what decided it). It is shown to the owner as your notes.')
        system += (' If you have a real view on where one of our stocks goes next, add "call": {"ticker":"CCJ","direction":"up|down",'
                   '"days":1-10}. Calls are scored against what the stock actually does and shown on your profile; skip it if unsure.')
        if role in ("pm", "risk", "review", "strategist", "auditor") and isinstance(payload, dict):
            tr = {k: v for k, v in (self.state.get("track") or {}).items() if v.get("calls", 0) >= 3}
            if tr:
                payload = {**payload, "teammates_track_record": {k: f"right {v['right']} of {v['calls']} calls" for k, v in tr.items()},
                           "how_to_use_track_record": "Lean on teammates whose calls have been right; question the ones who've been wrong."}
        offered = notes.ASK in system
        mates = feed.teammates()
        if mates:
            payload = ({**payload, "teammates_said": mates} if isinstance(payload, dict)
                       else f"{payload}\n\nTEAMMATES SAID:\n" + "\n".join(mates))
        user = payload if isinstance(payload, str) else json.dumps(payload, default=str)
        if MOCK:
            out = mock_answer(role, user)
            feed.post_agent(role, out, to)
            return out
        self._check_budget()
        model = self.cfg["models"][tier]
        kw = dict(model=model, max_tokens=max_tokens, system=HOUSE + "\n\nYOUR ROLE: " + system,
                  messages=[{"role": "user", "content": user}])
        # Claude 5.5 models think by default and thinking shares max_tokens: with our short limits the thinking used the
        # whole allowance and the answer came back EMPTY. Fast agents: thinking off. Smart agents: low effort + room.
        if "haiku" in model:
            kw["thinking"] = {"type": "disabled"}
        else:
            kw["output_config"] = {"effort": "low"}
            kw["max_tokens"] = max(max_tokens, 2500)
        if web_search:
            kw["tools"] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": web_search}]
        try:
            resp = self.client.messages.create(**kw)
        except Exception as e:
            msg = str(e).lower()
            if web_search and "tool" in msg:
                kw.pop("tools")
                resp = self.client.messages.create(**kw)
            elif "thinking" in msg or "output_config" in msg or "effort" in msg:  # model refused the setting: give it room instead
                kw.pop("thinking", None); kw.pop("output_config", None)
                kw["max_tokens"] = max(kw["max_tokens"], 3000)
                resp = self.client.messages.create(**kw)
            else:
                raise
        searches = 0
        try:
            searches = resp.usage.server_tool_use.web_search_requests or 0
        except Exception:
            pass
        cost = self._charge(role, model, resp.usage, searches)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        if not text.strip() or getattr(resp, "stop_reason", "") == "max_tokens":  # ran out of room: one retry with more
            kw["max_tokens"] = int(max_tokens * 2.5)
            resp = self.client.messages.create(**kw)
            cost += self._charge(role, model, resp.usage, 0)
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text") or text
        out = parse_json(text)
        out["_cost"] = round(cost, 4)
        try:
            notes.record(self.state, role, out, offered)
        except Exception as e:
            print("note check", e)
        try:  # record a scored prediction if the agent made one
            c = out.get("call")
            if isinstance(c, dict) and str(c.get("direction", "")).lower() in ("up", "down"):
                t = str(c.get("ticker", "")).upper()
                px = (self.state.get("last_prices") or {}).get(t)
                calls = self.state.setdefault("calls", [])
                day = str(dt.date.today())
                if px and not any(x["role"] == role and x["ticker"] == t and x["date"] == day for x in calls):
                    calls.append({"role": role, "ticker": t, "direction": c["direction"].lower(), "days": max(1, min(10, int(c.get("days") or 5))),
                                  "date": day, "price": px, "result": None})
                    del calls[:-600]
        except Exception as e:
            print("call record", e)
        feed.post_agent(role, out, to)
        if out.get("watch"):
            try:
                import desk_memory
                desk_memory.watch_add(out["watch"], role)
            except Exception:
                pass
        return out

    def record(self, entry):
        entry["time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        self.log.append(entry)
        del self.log[:-250]

    # ---------------- 1 scout
    def scout(self, items):
        lines = "\n".join(f'{i["id"]} | {i["ticker"]} | {i["source"]} | {i["title"]} | {i["summary"][:180]}' for i in items)
        return self.ask("scout", "fast",
                        "News Scout. Score each headline 0-10 for how likely it moves that stock several % over days. "
                        "7+ only for genuinely NEW, company- or sector-specific information (earnings/guidance, share "
                        "sales/dilution, big contracts, policy, M&A, major analyst moves, executive changes). Opinion "
                        "pieces, listicles, price recaps and rehashes score 0-3 and novelty 'stale'. Some headlines are about "
                        "RELATED companies (source says 'related to X'): CCJ's supply chain (Constellation CEG and Vistra VST "
                        "run reactors that buy uranium; Centrus LEU enriches it; BWXT makes reactor parts; Oklo builds small "
                        "reactors) or MU's biggest memory customer (NVIDIA). Score those for their effect on the traded stock "
                        "(e.g. a big new reactor contract is demand for CCJ's uranium). "
                        '{"items":[{"id":"","ticker":"","materiality":0,"novelty":"new|follow_up|stale","direction":"up|down|neutral",'
                        '"event_type":"earnings|policy_tariff|war_geopolitics|contract_deal|supply|analyst|offering_dilution|other","why":"<12 words"}]}',
                        lines, max_tokens=1800).get("items", [])

    # ---------------- 2 investigator
    def investigator(self, t, material, recent, chart):
        return self.ask("investigator", "smart",
                        f"Investigator for {t}. Decide if this news gives an edge now: is it new or already priced in "
                        "(compare the price move since publication), will it matter for days/weeks, good or bad? Use web "
                        "search only to confirm facts or find the primary source. "
                        '{"summary":"2 sentences","novelty":"new|partly|priced_in","direction":"up|down|neutral",'
                        '"durability":"one_day|days|weeks","confidence":0,"key_risk":"","trade_idea":"buy|avoid|exit|none"}',
                        {"material_news": material, "other_recent_headlines": recent[:12], "chart": chart},
                        web_search=self.cfg["news_analyst_web_searches"])

    # ---------------- 3 filings
    def filings(self, t, filings):
        return self.ask("filings", "fast",
                        f"Filings Analyst for {t}. Classify each SEC filing and say what it means for the stock. "
                        "Key types: 8-K 2.02 results, 1.01 material agreement, 5.02 officer change, 6-K (Canadian "
                        "filers like Cameco), F-10/S-3/424B prospectus = share sale/dilution, Form 4 insider trades. "
                        '{"filings":[{"title":"","type":"earnings|dilution|insider|contract|officer|routine|other",'
                        '"impact":"bullish|bearish|neutral","note":""}],"overall":""}', filings, max_tokens=700)

    # ---------------- 4,5,6 morning intelligence
    def whale_watcher(self, intel):
        return self.ask("whale", "fast",
                        "Whale Watcher. From options positioning, short volume, short interest and insider trades, "
                        "describe how big money is positioned in each stock and what it implies for the next 1-2 weeks. "
                        "Use put/call walls only as levels to watch, gamma only as 'expect bigger/smaller swings', and "
                        "say 'no signal' when there isn't one. "
                        '{"tickers":{"CCJ":{"bias":"bullish|bearish|neutral","conviction":"low|med|high","watch_levels":[],'
                        '"swing_expectation":"bigger|normal|smaller","notes":""}}}', intel, max_tokens=900)

    def macro(self, market, calendar):
        return self.ask("macro", "fast",
                        "Macro & Sector Analyst. From S&P trend, VIX, futures, overnight peers (SK Hynix/Samsung for MU, "
                        "Kazatomprom and uranium funds for CCJ, the physical uranium trust and BWXT for LEU, Vistra/Talen/utilities and Japan's Kansai Electric for CEG; Asia's close predicts the opening gap but not the move after the open), crypto's "
                        "weekend move (hints at Monday's opening gap, which tends to partly fade), holidays, Fed days, opex and "
                        "earnings dates, set today's risk level and notes per stock. Overnight peer moves often just "
                        "echo yesterday's US session; don't over-read them. "
                        '{"risk_level":"low|normal|elevated|high","market_note":"","tickers":{"CCJ":{"note":"","event_risk":""}}}',
                        {"market": market, "calendar": calendar}, max_tokens=700)

    def crowd(self, data):
        return self.ask("crowd", "fast",
                        "Crowd Analyst. From Reddit/WSB mention counts and analyst consensus/targets, flag crowding "
                        "('don't chase') or neglect. Analyst targets lag; mention spikes tend to reverse. "
                        '{"tickers":{"CCJ":{"chase_risk":"low|med|high","note":""}}}', data, max_tokens=500)

    # ---------------- 7,8,9 strategy
    def technical(self, t, chart):
        return self.ask("technical", "fast",
                        f"Technical Analyst for {t}: trend and entry quality. "
                        '{"trend":"up|down|sideways","setup":"good_entry|chase|falling_knife|neutral","comment":""}',
                        chart, max_tokens=250)

    def level_trader(self, setups, context):
        return self.ask("level", "fast",
                        "Level Trader. The code found support-level setups: a resting limit buy just above a support zone, "
                        "a tight stop under it, target at the next resistance. For each, decide ARM or SKIP. Skip when "
                        "the zone looks likely to break (bad news, falling knife, heavy put buying, event risk), or when "
                        "an options put wall or other level sits just below the zone in a way that suggests the stop "
                        "will get run. You cannot move prices. "
                        '{"setups":{"CCJ":{"decision":"ARM|SKIP","reason":""}}}',
                        {"setups": setups, "context": context}, max_tokens=600)

    def core_manager(self, data):
        return self.ask("core", "fast",
                        "Core Manager. Weekly note on the long-term holdings: is each stock's long-term thesis intact? "
                        "Weights are set by a fixed rule (half weight when >3% under the 200-day average); you only "
                        "comment, and may flag 'thesis_broken' for the owner to review. "
                        '{"tickers":{"CCJ":{"thesis":"intact|watch|thesis_broken","note":""}},"summary":""}', data, max_tokens=600)

    # ---------------- 10,11 decision
    def risk(self, data):
        return self.ask("risk", "fast",
                        "Risk Manager. Hard limits are enforced in code (each trade is one of 3 equal slots of the account, "
                        "a stop ~1.6% under entry on every trade, "
                        "risk halved at -10% and kill switch at -20% from peak, no day/week loss pauses by owner's choice, "
                        "no new trades 2 days before earnings, exit trading positions the day before earnings). Your job: veto or shrink anything "
                        "unwise given concentration (all three stocks swing 2-3x the market), events and the account's "
                        "recent results. "
                        '{"decisions":{"CCJ":{"veto":false,"size_mult":1.0,"reason":""}}}', data, max_tokens=500)

    def challenge(self, t, decision, context):
        return self.ask("risk", "fast",
                        "Risk Manager, second opinion. The Portfolio Manager just made a call on one stock. Argue the other "
                        "side honestly: what could make this call wrong? Then decide whether you object. Object only for a "
                        "concrete reason (the news is stale, the call ignores the stop or earnings, it chases a move), not "
                        "for style. "
                        '{"object":false,"counter_action":"HOLD|SELL|SKIP","reason":"","say":""}',
                        {"ticker": t, "pm_decision": decision, **context}, max_tokens=400, to="pm")

    def answer_owner(self, data):
        return self.ask("pm", "fast",
                        "Portfolio Manager answering the OWNER, who just posted to the team and wants you to look for a trade "
                        "right now. The code already re-scanned every stock; you get the setups it found and why the others "
                        "have none. Answer the owner directly in plain English: what the team found, what it is doing (a buy "
                        "only rests at a real support level with a stop; you cannot buy at market or skip the stop), and what "
                        "would change the picture. Be honest when the answer is 'nothing safe to buy yet'. "
                        '{"say":"","to":"You","post":"one-line public announcement of the outcome"}', data, max_tokens=600, to="owner")

    def pm(self, data, kind="morning"):
        sys = ("Portfolio Manager. Make the final call. Prefer no trade over a mediocre one; never force trades. "
               + ("MORNING PLAN: for each proposed setup decide ARM or SKIP and a size_mult 0-1 (cannot exceed Risk "
                  "Manager's). " if kind == "morning" else
                  "EVENT DECISION for one stock: BUY a conviction trade when the news plus the desk notes give you a real, "
                  "specific reason the stock goes up in the next days (think like the best nuclear specialist: who is behind "
                  "it, what it changes, what happened the last times, is it priced in); SELL an open trade on clearly bad, "
                  "durable news; or HOLD. Be bold when you see it and honest when you don't: every call is scored. ")
               + '{"decisions":{"CCJ":{"action":"ARM|SKIP|BUY|SELL|HOLD","size_mult":1.0,"confidence":0,"conviction":0,'
                 '"target_pct":10,"stop_pct":8,"days":5,"reason":"2 plain-English sentences for the owner"}},"plan_summary":""}')
        return self.ask("pm", "smart", sys, data, max_tokens=900)

    # ---------------- 14,15 review
    def reviewer(self, packet, weekly=False):
        return self.ask("review", "smart",
                        "Daily Reviewer, writing for the owner (a college student). Plain English, honest about losses "
                        "and luck. Cover: account today and this week vs the +5% goal, core vs trading, each open "
                        "position and its stop, every order/trade and agent decision today, vs buy-and-hold, and what "
                        "to watch tomorrow" + (" plus a recap of the week and one lesson." if weekly else ".") +
                        ' Under 280 words. {"headline":"<=90 chars","review_markdown":""}', packet, max_tokens=1300)

    def postmortem(self, data):
        return self.ask("postmortem", "fast",
                        "Post-mortem Analyst. Judge the DECISION, not the outcome (a good trade can lose and a bad one can "
                        "win). Classify the result: bad_setup (the rules or level were wrong), bad_execution (fill, "
                        "timing, slippage), regime_mismatch (market environment wrong for this setup), news_shock "
                        "(unforeseeable news), or noise (normal randomness of a valid setup; expected often with "
                        "~25-35% win-rate setups). Only give a lesson if it is specific and would change a future "
                        "decision; otherwise lesson = 'none'. "
                        '{"verdict":"bad_setup|bad_execution|regime_mismatch|news_shock|noise","decision_quality":"good|ok|poor",'
                        '"what_happened":"1-2 sentences","lesson":"one sentence or none"}', data, max_tokens=350)

    def strategist(self, data):
        return self.ask("strategist", "smart",
                        "Strategist. Like a specialist commodity trader, connect the dots: tariffs, trade wars, sanctions, "
                        "wars, energy and nuclear policy, AI data-center power demand, supply disruptions (mines, enrichment, "
                        "chip fabs), and the desk's own MEMORY of how each stock reacted to each event type. Use web search "
                        "to check what is scheduled (policy decisions, deadlines, earnings, auctions). Write at most 3 theses "
                        "that are specific and testable: what you expect, the catalyst and date, what would confirm or kill "
                        "it, and how to express it. Expressions: 'stock' (the desk's rules may act) or 'option_idea' (owner "
                        "alert only, must be a capped-loss structure; the account is ~$1,000 so cost matters). Say 'no strong "
                        "thesis this week' when that is the truth. "
                        '{"theses":[{"tickers":["CCJ"],"thesis":"","catalyst":"","catalyst_date":"YYYY-MM-DD or unknown",'
                        '"direction":"up|down|volatile","confirms":"","kills":"","expression":"stock|option_idea","conviction":"low|med|high"}],'
                        '"summary":""}', data, web_search=3, max_tokens=1500)

    def auditor(self, scorecard):
        return self.ask("auditor", "smart",
                        "Performance Auditor. Using the scorecard (results by setup type, by who initiated, vetoed "
                        "setups and what they would have done, agent costs vs value added), say plainly what is "
                        "working, what isn't, and what to change. With few trades, say the sample is too small. "
                        '{"grades":{"level":"","dip":"","news":"","core":"","vetoes":"","agents_worth_cost":""},'
                        '"recommendations":[""],"summary":""}', scorecard, max_tokens=900)


def parse_json(text):
    """Model JSON -> dict. Tolerates code fences and raw newlines inside strings; if the JSON is still broken
    (e.g. cut off), rescue the readable fields so the team chat shows words, not code."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        for strict in (True, False):
            try:
                return json.loads(m.group(0), strict=strict)
            except json.JSONDecodeError:
                pass
    out = {"_raw": (text or "")[:1500]}
    for k in ("say", "to", "headline", "review_markdown", "summary", "post", "market_note", "risk_level"):
        mm = re.search(r'"%s"\s*:\s*"((?:[^"\\]|\\.)*)' % k, t, re.S)
        if mm:
            try:
                out[k] = json.loads('"' + mm.group(1) + '"', strict=False)
            except Exception:
                out[k] = mm.group(1).replace('\\"', '"')
    return out


def mock_answer(role, user):
    T = ["CCJ", "LEU", "CEG"]
    if role == "scout":
        ids = re.findall(r"^(\w{16}) \| (\w+) \|", user, re.M)
        return {"items": [{"id": i, "ticker": t, "materiality": 8 if k == 0 else 2, "novelty": "new" if k == 0 else "stale",
                           "direction": "down", "why": "mock"} for k, (i, t) in enumerate(ids)]}
    m = {
        "investigator": {"summary": "Mock: new negative news.", "novelty": "new", "direction": "down", "durability": "days",
                         "confidence": 60, "key_risk": "mock", "trade_idea": "avoid"},
        "filings": {"filings": [], "overall": "Mock: routine."},
        "whale": {"tickers": {t: {"bias": "neutral", "conviction": "low", "watch_levels": [], "swing_expectation": "bigger",
                                  "notes": "Mock whale note."} for t in T}},
        "macro": {"risk_level": "elevated", "market_note": "Mock: market below 200-day.", "tickers": {t: {"note": "mock", "event_risk": ""} for t in T}},
        "crowd": {"tickers": {t: {"chase_risk": "low", "note": "mock"} for t in T}},
        "technical": {"trend": "down", "setup": "falling_knife", "comment": "Mock technicals."},
        "level": {"setups": {t: {"decision": "ARM", "reason": "Mock: zone looks clean."} for t in T}},
        "core": {"tickers": {t: {"thesis": "intact", "note": "mock"} for t in T}, "summary": "Mock core note."},
        "risk": {"decisions": {t: {"veto": False, "size_mult": 1.0, "reason": "mock"} for t in T}},
        "pm": {"decisions": {t: {"action": "ARM", "size_mult": 1.0, "confidence": 55, "reason": "Mock decision."} for t in T},
               "plan_summary": "Mock plan."},
        "review": {"headline": "Mock review", "review_markdown": "**Mock review.**"},
        "auditor": {"grades": {}, "recommendations": ["Mock: sample too small."], "summary": "Mock audit."},
        "strategist": {"theses": [{"tickers": ["CCJ"], "thesis": "Mock thesis.", "catalyst": "mock", "catalyst_date": "unknown",
                                   "direction": "volatile", "confirms": "x", "kills": "y", "expression": "stock", "conviction": "low"}],
                       "summary": "Mock strategy note."},
        "postmortem": {"verdict": "noise", "decision_quality": "good", "what_happened": "Mock: level broke on a market-wide dip.", "lesson": "none"},
    }
    SAY = {
        "macro": "Practice line. Live, I read the S&P trend, VIX, futures and the calendar, then set today's risk level for the team.",
        "whale": "Practice line. Live, I check options positioning, short volume and insider buys, and tell the team if big money leans one way.",
        "crowd": "Practice line. Live, I watch Reddit and analyst chatter; a sudden buzz spike usually fades within weeks, so I flag chasing risk.",
        "level": "Practice line. Live, I judge whether each support level is clean (touched before, not mid-crash) and say ARM or SKIP.",
        "investigator": "Practice line. Live, I read the headline and the filings around it and tell the team if it is new, durable news or a rehash.",
        "filings": "Practice line. Live, I read the SEC filing itself: contracts, insider trades, share sales.",
        "pm": "Practice line. Live, I weigh what the team said and make the call: hold, sell, or cancel the waiting buy.",
        "risk": "Practice line. Live, I argue the other side of the Portfolio Manager's call and object if there is a concrete reason.",
        "review": "Practice line. Live, I write the end-of-day review: what happened, what the bot did, and why.",
        "auditor": "Practice line. Live, I grade the week's setups once there are enough trades to grade.",
        "strategist": "Practice line. Live, I propose up to three theses for the coming weeks, each with what would prove it wrong.",
        "postmortem": "Practice line. Live, I explain why a closed trade won or lost: bad setup, bad execution, the market, news, or plain noise.",
        "technical": "Practice line. Live, I read trend and momentum for the team.",
        "core": "Practice line. Live, I check whether the long-term CCJ thesis still holds.",
        "scout": "Practice line. Live, I score each new headline 0-10 for how much it could move the stock.",
    }
    TO = {"macro": "Nowcast", "whale": "Macro Analyst", "crowd": "Whale Watcher", "level": "Macro Analyst",
          "investigator": "News Scout", "filings": "News Investigator", "pm": "News Investigator", "review": "Account Officer",
          "auditor": "Reviewer", "strategist": "Auditor", "postmortem": "Execution Trader"}
    if role == "researcher":
        return {"say": "Practice line. Live, I propose ideas the code can test on our practice trades, then write up what we learned.",
                "to": "Risk Manager", "_cost": 0,
                "ideas": [{"feature": "group_up", "op": "==", "value": "false", "claim": "worse", "why": "a falling sector breaks supports"},
                          {"feature": "ret5d_pct", "op": "<", "value": -6, "claim": "worse", "why": "buying into a hard week catches falling knives"}],
                "notes": []}
    if role == "pm" and ("owner_post" in user or "boss_post" in user):
        return {"say": "Practice line. Live, I answer your post: what the scan found, what we'll do, and what would change it.",
                "to": "You", "post": "Practice: scan done.", "_cost": 0}
    if role == "risk" and "pm_decision" in user:
        return {"object": False, "counter_action": "HOLD", "reason": "practice", "say": SAY["risk"], "to": "Portfolio Manager", "_cost": 0}
    out = dict(m.get(role, {}))
    out["say"] = SAY.get(role, "Practice line.")
    out["to"] = TO.get(role, "team")
    out["_cost"] = 0
    return out
