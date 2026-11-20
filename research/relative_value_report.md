# Relative-value research on the CCJ / TSM / ETN basket (2026-11-20)

Criteria were pre-registered before any test (`relative_value_prereg.md`): Deflated Sharpe Ratio (DSR) >= 0.95
with N = all trials, net-of-cost (0.20% round trip, 1%/yr short borrow) return > 0 in both halves of the
out-of-sample period, max drawdown <= 20% (long-only overlays: no worse than the equal-weight trio), and long-only
implementability. Out-of-sample = 2019-01-01 to 2026-11-19, walk-forward estimates only.

## Verdict: rejected. Nothing promoted, not even to shadow mode.

### 1. The basket is not cointegrated (prerequisite failed)
| Test | Result |
|---|---|
| Engle-Granger, full sample | CCJ~TSM p=0.35, CCJ~ETN p=0.11, TSM~ETN p=0.41 |
| Johansen trace (trio), full sample | does not reject "no cointegration" at 5% |
| Rolling 2-year windows (40) | pairs cointegrated in 5-8% of windows (about the 5% false-positive rate); trio in 20% (needed >= 50%) |
| Spread half-life | pairs 124-211 trading days; trio 87 days full-sample (needed 5-60) |

The three stocks share a theme and move together day to day (correlation ~0.5), but their price **levels** drift
apart for years. Correlation is not cointegration: nothing pulls the spread back on a tradable timescale.

### 2. Trading the spread anyway (16 trials, net of 0.20% costs)
| Trial family | Best result | DSR | Fails |
|---|---|---|---|
| Trio Johansen spread, long-short (4) | -2.6%/yr, max DD -41% | 0.04 | everything |
| Pair z-score, long-short (6) | ETN/TSM 60-day: +7.2%/yr, Sharpe 0.56, DD -20% | 0.57 | DSR, DD, needs shorting |
| Long-only cheap-leg tilt (4) | +0.7%/yr vs equal weight (active) | 0.16 | DSR (2 of 4 also fail halves/DD) |
| Long-only laggard rotation (2) | -1.2%/yr vs equal weight, DD -40% to -46% | 0.12 | DSR, halves, DD |
| Benchmark: equal-weight trio | +32.4%/yr, Sharpe 1.05, DD -34% | n/a | n/a |

N = 16, cross-trial daily Sharpe variance 3.05e-4, so the DSR hurdle is an annualized Sharpe of 0.50.
At 0.10% costs the best trial (ETN/TSM pair) reaches DSR 0.61: still a fail.

### 3. Same standard applied to the live strategy (Patient Levels, trio, 3 slots, 0.20% costs)
| Version | Tune half | Test half | Test Sharpe | Max DD | DSR (test, N=30) |
|---|---|---|---|---|---|
| 5-day resting orders (LIVE) | +38%/yr | +27%/yr | 1.75 | -10% | **0.80** |
| 7-day | +36%/yr | +31%/yr | 2.01 | -10% | 0.89 |
| old 1-day | +25%/yr | +7%/yr | 0.52 | -17% | 0.23 |
| require 2x reward | +22%/yr | +2%/yr | 0.23 | -16% | 0.14 |

30 variants of the level rule were tested this session; their spread of Sharpe ratios sets a hurdle of 1.11.
The live rule passes the net-of-cost and drawdown tests but **not** DSR 0.95. Status: promising, unproven.
(Caveats: the test half is ~1 year of hourly data; trade P&L is booked on exit days.)

## What changed in the bot
- `research/trial_ledger.json`: every variant ever tested, per strategy, with the cross-trial Sharpe variance.
  Every future idea adds to it, which raises the bar for everything.
- `gate.py` + Desk tab: the bot scores its **own paper record** the same way after every close.
  Real-money buys are blocked until it passes (`live_override: true` lets the owner overrule it).
- Relative value is marked rejected in the ledger.

## How long the gate takes (arithmetic)
If live results match the backtest test half (Sharpe 1.75) against the 1.11 hurdle, DSR reaches 0.80 after about
440 trading days (~1.75 years) and 0.95 after about 1,700 (~6.7 years). A strict gate after a wide search is slow
by design. Options: keep it strict; use staged sizing (e.g. 25% size at DSR 0.5, 50% at 0.8, full at 0.95); or
stop adding variants. Fewer tests in the future means a lower hurdle for whatever gets tested next.
