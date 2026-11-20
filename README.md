# Patient Levels · Trio (Swing Desk v8)

**One simple rule, maximized.** Put a buy order just above the nearest support level, leave it there for up
to 5 trading sessions, and sell at the next resistance, at a stop just under the support, or after 3 days.
Everything else in this repo (17 Claude roles, intel, memory, ranking, guards, the Control Center) is
preparation around that one rule.

## The trio: CCJ + TSM + ETN, synchronized
- **Fuel → chips → power gear:** Cameco (uranium for the nuclear plants that will power AI), TSMC (makes the AI
  chips), Eaton (the electrical equipment that feeds data centers). All three passed the "works in both halves"
  check; MU failed it.
- **One system, not three bets:** the trio shares one **pulse**. When the basket is above its 10-day average,
  every buy gets a bigger slot (1.2×); below it, a smaller one (0.8×). A stock that dips while its two partners
  rise gets 1.15× more; one that dips while its partners all sell off more than 2% gets 0.7×. Never zero, so the
  bot always keeps trading. Tested: the pulse helped in **4 of 4** tune/test checks across two trios. In the Lab, sync
  sizing turned $1,000 into **$3,000 versus $2,730** with equal sizing over 2.8 years, with a smaller worst drop
  (−8% vs −9%). These are hindsight-tested numbers; expect less live.
- **When the trio breaks down together** (like right now: CCJ and ETN below every recent support), the rule simply
  waits. No floor, no buy.
- The other 20 stocks still get ranked every Monday as a **scoreboard**, for reference only. Change the trio in Settings.

## Why this rule (research/, about 2.8 years of hourly data, Jan 2024 to Nov 2026)
- Tuned on the first half and tested on the second. Letting the order **rest for days** instead of hours was the
  only change that improved both halves on both trios tested. Out-of-sample t-scores were above 3.
- It made money in the second half on **19 of 20** stocks. Median **+0.48% per trade** after 0.1% costs. It stays
  positive even when fills require price to trade 0.2% *through* the order.
- Upgrades that **failed** the test, and were left out: requiring 2× reward (looked best in half one, lost money in
  half two), volume filters, multi-timeframe confluence, trailing stops, taking half off early, and the old 1-day orders.
- **Weak spot:** slow, grinding selloffs. The current one (since Oct 28, 2026) is the worst stretch in the sample
  (−0.47% per trade). Quick V-shaped crashes like April 2025 were fine (+0.98%).
- The simulated $1,000 account with 3 slots made roughly +60–90% a year with a worst drop of 15–25%, and +5% weeks
  about 8–15% of the time. Treat these as upper bounds: it was a strong market, and the stocks were picked with hindsight.

## How it runs
| When | What |
|---|---|
| Monday 8am | Updates the watchlist scoreboard (20 stocks) for reference. The bot trades the **fixed trio** (`lineup_mode: "fixed"`). Set `lineup_mode` to `"rank"` to let it pick the top stocks instead. |
| ~9:31 | Re-places stops and resting buys (Alpaca day orders expire nightly), writes the intel brief, the agents give their read, the options radar runs |
| Every 30 min | Finds new support levels; keeps orders resting on the setups **closest to filling**, within free slots and settled cash |
| Any time | Target hit: sell. Stop: rests at the broker. Big bad news: the agents can cancel a waiting buy or exit a trade (they can never buy) |
| 3:40pm | Trades held 3 days are closed; shadow setups are logged |
| After close | Review, memory, post-mortems. Fridays: Strategist theses, Auditor, learning loop |

Money: 3 slots (one-third of the account each, scaled 0.5×–1.4× by the trio pulse), long only, no margin, no options.
Guards: a stop on every trade, a malfunction guard, risk halved at −10% from peak, a kill switch at −20%. There are no pauses after a bad day.

## Control Center (docs/index.html, served by GitHub Pages)
- **Today:** a price ladder for each stock showing where price is versus the resting buy, stop and target, plus trades, orders and the review
- **Charts:** hourly candles with the zone and order lines, and the rule's past trades marked
- **Lab:** move the sliders and the rule re-runs in your browser on 2.8 years of 20 stocks (same engine as the bot,
  verified trade-for-trade). It compares the tune half with the test half and warns you when a setting is just luck
- **Desk:** lineup ranking, agent decisions, Strategist theses, options radar, post-mortems, memory, headlines
- **Settings:** edit the main settings, then download or copy a new config.json

## Setup (same as before)
Alpaca **paper** keys, a Claude API key, a GitHub repo (public = free run time), and the ntfy app. Add the secrets
`ALPACA_KEY`, `ALPACA_SECRET`, `ANTHROPIC_API_KEY` and `NTFY_TOPIC`. Turn on Pages from `/docs`.
Run `test-notify`, `test-agents`, `test-broker`, then `first-run`.
For fast reactions, use always-on mode on a small server: see `deploy/` and set `"runner": "vm"`.
Go live only after paper results look like the Lab's test half.

## v10 (2026-11-20): CCJ correlation research, nowcast, feedback loop
- Backtest fix: when an open gapped below the stop, both engines (patient.py, web/engine.js) booked the exit AT the stop, i.e. above the fill. Exits now happen at the fill price. About 12% of backtest profit was fake. Out-of-sample: +24%/yr, Sharpe 1.56, DSR 0.67 (was 0.80).
- `signals.py`: morning Asia nowcast (expected opening gap, information only), `gap_risk` "Open watch" alerts, Friday `weekly_drift` against `research/signals_registry.json`.
- `run.arm`: never rests a buy when the price is already at or below its stop.
- Research: `research/ccj_fetch.py`, `ccj_corr.py`, `ccj_leadlag.py`, `ccj_overlay.py`. 88 trials logged in trial_ledger.json; no tradable cross-asset survivor.

## v11 (2026-11-20): Feed, fuel-chain trio, Shadow Desk, Options Recorder
- **Feed tab** (first tab): every agent and code role posts in plain words, newest first; filter by who, by stock, or search. Posts are buffered and saved with the state (no extra calls).
- **Trio = uranium fuel chain:** CCJ (mines), LEU (enriches), CEG (burns). Backtest 2.8y: +0.44%/trade, 0.267R (old trio +0.61%, 0.375R). Chosen for linked-but-distinct news, not rank: stock rank did not persist (research/universe_wide.py).
- **Shadow Desk** (`shadow.py`): after each close, every Patient Levels setup on 52 stocks is replayed with no money; only fully closed trades are recorded. Fridays: patterns that held in both halves of the record are posted as candidates.
- **Options Recorder** (`options_rec.py`): ~15:45 ET daily, option chains (<=70 days) for the trio to `data/options/YYYY-MM-DD.csv.gz` (committed by the workflow).
- Last ~3 months were bad for the strategy everywhere (52 stocks: -0.19R/trade, 31% wins; new trio -0.38R, 23% wins) - the uranium/AI selloff broke support after support.

## v12 (2026-11-20): redesign + Team chat
- New look (spent-fuel-pool dark, Cherenkov blue), the fuel chain CCJ -> LEU -> CEG at the top, three main buttons:
  **What's happening** (plain-English page built from the bot's state, no AI cost), **Posts** (the feed), **Team chat**.
- **Team chat:** each decision is a group chat (`feed.thread`): morning meeting, every news decision, daily review, trade postmortems.
  Agents receive what teammates said (`teammates_said`) and must reply with a plain-English `say`, naming who they agree/disagree with.
  News decisions now get a Risk Manager second opinion; if it objects, the Portfolio Manager must answer before the final call (one round, budget-capped).
- `setup_status`: the bot records why each stock has no buy (no support below price, earnings, skew veto, Level Analyst skip).

## v13 (2026-11-20): simple home
- One quiet column: the team as story circles (lit = spoke today; tap = that agent's posts), the portfolio value with a
  Today / Week / All chart (`equity_intraday`, saved every market-hours run), one "right now" sentence, then two tabs:
  **Trades** (holding now, waiting to buy, closed trades) and **Team** (group chats + posts in one timeline).
- Levels, Charts, Lab, Desk, Settings moved under "Under the hood".
- `first-run` now also forces the daily review, so the team chats and the practice-trade replay appear right after setup.

## v14 (2026-11-20): posts, DMs, and posting to the team
- **Laptop layout:** portfolio + chart + trades on the left (sticky), the team's posts on the right; stacks on a phone.
- **Posts:** every announcement is an Instagram-style post with a headline block (orders, fills, scans, practice trades, options saved, weekly check).
- **Messages (chat bubble, top right):** inbox of every agent -> an agent's page with its own notes (the structured reasoning behind each message),
  its one-on-one DMs with other agents, and the group chats it was in. Agents now say who they're answering (`to`), so DMs are real.
- **Post to the team:** the composer posts to ntfy topic `<NTFY_TOPIC>-inbox` (also works from the ntfy phone app). Each run reads it,
  re-scans all three stocks right away, checks any other ticker you name (info only), and the Portfolio Manager answers you in the feed
  and on your phone. Posts can't break the rules (support + stop only); max 8 a day. Test locally: `python run.py owner-post "look at CCJ"`.

## v15 (2026-11-20): fixes, cheaper runs, more news
- Fixed: opening a group chat crashed the Messages panel (and made Back look broken). Back now walks inbox -> groups -> chat, also from a post's "View the conversation".
- **Cheaper:** scheduled GitHub runs are one quick pass every 15 min, 13-21 UTC (about 8am-5pm ET) -> ~1,500 min/month, inside the 2,000 free minutes for a private repo. Stops and buy orders rest at the broker between runs.
- **More news, filtered:** World Nuclear News, the NRC, the American Nuclear Society, the Federal Register (uranium, nuclear fuel), Cameco's own press releases, PR Newswire energy,
  plus Google News topic searches per stock (uranium price, Kazatomprom, Sprott, Westinghouse, HALEU, enrichment, Russian uranium ban, reactor restarts, data-center power deals).
  Every item is routed to CCJ/LEU/CEG by keywords; junk (quote pages, Form 144 spam, Iran/North Korea enrichment) is dropped; no feed can take more than 6 slots per run.
- **StockTwits:** bullish/bearish tags and latest messages for each stock go to the Crowd Reader every morning.

## v16 (2026-11-20): hawk mode (always-on, still ~free)
- Run on the Google Cloud **always-free e2-micro** VM (`deploy/setup_vm.sh`), then set the GitHub repo variable `RUNNER=vm`
  so scheduled GitHub runs stop. The daemon checks every **60 seconds** from 8am to 7pm ET.
- **Live prices:** Alpaca's free IEX trade stream (`hawk_stream`). A held trade touching its target, or a stock moving 1.5%+ within
  10 minutes, wakes the bot at once and triggers a full news sweep with a "Hawk alert" post.
- **News lanes:** fast lane every run (each stock's Yahoo feed, SEC filings, Cameco press room); slow lane every 10 minutes
  (nuclear-industry feeds, Google News topics, related companies). Claude is only called for headlines it hasn't seen.
- Daily price history is cached for 3 hours, so a per-minute check takes ~3-5 seconds instead of ~30.

## v17 (2026-11-20): 10-stock nuclear fuel chain + sector filter
- Lineup: CCJ NXE UEC DNN UUUU (mine), LEU (enrich), BWXT (reactor parts/fuel), CEG VST TLN (run plants). Still 3 trades at a time.
- Research (730 days, 3 slots): trio ~4 trades/week, 10-stock chain ~12/week. More trades but lower quality per trade (0.09R vs 0.19R)
  and much deeper drops without a filter (-46% / -32% by year). Adding SMR and OKLO made it worse.
- **Sector filter** (`sync.pulse_filter`): no NEW buys while the 10-stock basket is below its 70-hour average. Cut the worst drops to
  -14% / -20% and raised R per trade (0.27R over 2 years), but year-2 return fell from +21.8% to +6.5%. Mixed evidence: paper only.
- Options recorder now covers CCJ, LEU, CEG, NXE, VST. News keywords and searches added for every lineup stock.
