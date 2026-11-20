# Relative-value study: pre-registered promotion criteria
Written 2026-11-20 ~02:56 ET, BEFORE any relative-value test was run. Not to be edited after results.

## Basket
CCJ, TSM, ETN (the live trio). Daily closes 2015-01-01 to 2026-11-19 (adjusted). Log prices.

## Prerequisite (is there anything to trade?)
- The basket (Johansen trace, 5%) or a pair (Engle-Granger, 5%) must show cointegration in **at least 50% of
  rolling 2-year windows**, not just the full sample.
- Spread half-life (OU fit) between **5 and 60 trading days**.
If this fails, strategies are still tested (to measure what "trading a non-cointegrated spread" costs) but none
can be promoted.

## Method
- Walk-forward only: hedge ratios / means / volatilities estimated on trailing data; trades decided on day t close,
  executed day t+1 close. No full-sample parameters.
- Out-of-sample evaluation period: 2019-01-01 to 2026-11-19 (2015-2018 is warm-up/estimation only).
- Costs: 0.10% and **0.20%** round trip per leg trade (decision uses 0.20%); short legs pay 1%/yr borrow.
- Every variant run counts as a trial. N = total trials across the whole study, including discarded ones.

## Promotion criteria (all must pass, at 0.20% cost)
1. **Deflated Sharpe Ratio >= 0.95** (Bailey & Lopez de Prado 2014) on daily out-of-sample net returns, using
   N = all trials and the cross-trial variance of Sharpe ratios, with skew/kurtosis adjustment.
   For long-only overlays the DSR is computed on **active returns** (overlay minus equal-weight trio).
2. **Net-of-cost annual return > 0 in both halves** of the OOS period (2019-2022 and 2023-2026).
3. **Max drawdown <= 20%** of the strategy's own capital; for long-only overlays, max drawdown **no worse than**
   the equal-weight trio.
4. **Implementable in the account:** long-only, cash account, fractional shares (no shorting). Long-short variants
   are measured as research references only and cannot be promoted.

## What promotion means
Pass -> **shadow mode** in the bot (tracked, no money) for >= 3 months; live sizing only if shadow results stay
inside the backtest's range. Fail -> documented and not used.

## Explicitly not a criterion
Raw return targets (e.g. "+5% per week") are not used to judge anything in this study.
