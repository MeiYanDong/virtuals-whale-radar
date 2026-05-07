# Launch Strategy Backtest - 2026-05-07

## Scope

- Goal: test a launch-window auto-buy idea for 98-minute tax projects.
- Strategy family: buy `50 VIRTUAL` when current tax-adjusted FDV is below whale-board weighted average cost.
- Production trading: not enabled.
- Production DB touched: no.
- Test source: replay `samples.jsonl` files generated from isolated replay DBs.
- Primary target sample: SR / `Strike Robot` / Virtuals ID `70972`.

## Backtest Tool

Added read-only script:

```bash
scripts/ops/backtest_launch_strategy.py
```

The script reads replay sample JSONL files and simulates parameter grids:

- whale-board spent threshold
- max allowed tax rate
- FDV discount versus weighted whale-board cost
- normal cooldown
- burst-buy limit and burst cooldown
- max project spend
- minimum cost rows / whale rows

Assumptions:

- Signal FDV: `estimatedFdvWanUsdWithTax`.
- Entry cost: tax-adjusted FDV at the sample where a buy is triggered.
- Mark-to-market: later `liveFdvUsd / 10000`.
- Trade size: `50 VIRTUAL` per simulated buy.
- This is a strategy filter test, not execution/slippage simulation.

## Test Runs

| Report | Source | Result |
| --- | --- | --- |
| `data/backtests/sr-launch-strategy-grid-20260507.json` | SR 144-sample full replay | 17,496 strategies, 2,592 triggered |
| `data/backtests/sr-launch-strategy-aggressive-grid-20260507.json` | SR 144-sample full replay | 25,272 strategies, 14,904 triggered |
| `data/backtests/tds-launch-strategy-grid-20260507.json` | TDS 144-sample full replay | 1,152 strategies, 0 triggered |
| `data/backtests/isc-early-launch-strategy-grid-20260507.json` | ISC early 10m replay | 1,440 strategies, 960 triggered under low thresholds |
| `data/backtests/sr-highres-launch-strategy-grid-20260507.json` | SR 1,034-sample high-resolution full replay | 17,496 strategies, 2,160 triggered |

The high-resolution SR replay used:

- `753` tx
- `602` parsed events
- `602` inserted events
- `1,034` samples
- `logErrors=[]`
- historical `eth_call` supported

## Key Cases

### User Baseline

Parameters:

- `boardSpentV >= 100,000`
- `buyTaxRate <= 92`
- `estimatedFdvWanUsdWithTax <= boardCostWanUsd`
- buy `50 VIRTUAL`
- normal cooldown `60s`
- if 2 buys happen within `120s`, cooldown `600s`
- max project spend `300 VIRTUAL`

High-resolution SR result:

- Buy count: `2`
- Total spend: `100 VIRTUAL`
- Final PnL: `+38.050128 VIRTUAL`
- Final PnL pct: `+38.0501%`
- First buy:
  - tax `92%`
  - board spent `132,032.472 V`
  - entry tax-adjusted FDV `359.711454 万 USD`
  - board weighted cost `364.638858 万 USD`
- Second buy:
  - tax `91%`
  - board spent `159,224.769 V`
  - entry tax-adjusted FDV `376.075892 万 USD`
  - board weighted cost `377.853186 万 USD`

### More Aggressive 5W Entry

Parameters:

- `boardSpentV >= 50,000`
- `buyTaxRate <= 98`
- `estimatedFdvWanUsdWithTax <= boardCostWanUsd * 0.98`
- buy `50 VIRTUAL`
- cooldown `180s`
- max project spend `300 VIRTUAL`

High-resolution SR result:

- Buy count: `1`
- Total spend: `50 VIRTUAL`
- Final PnL: `+41.912947 VIRTUAL`
- Final PnL pct: `+83.8259%`
- Entry:
  - tax `93%`
  - board spent `54,966.025 V`
  - entry tax-adjusted FDV `276.145245 万 USD`
  - board weighted cost `331.375072 万 USD`

Interpretation:

- This was best on SR by capital efficiency.
- It is also more likely to overfit SR, because it enters before whale-board spend reaches `100,000 V`.

### Conservative 10W Single-entry Variant

Parameters:

- `boardSpentV >= 100,000`
- `buyTaxRate <= 98`
- `estimatedFdvWanUsdWithTax <= boardCostWanUsd * 0.98`
- cooldown `180s`
- max project spend `300 VIRTUAL`

High-resolution SR result:

- Buy count: `1`
- Total spend: `50 VIRTUAL`
- Final PnL: `+20.021538 VIRTUAL`
- Final PnL pct: `+40.0431%`
- Entry:
  - tax `90%`
  - board spent `164,791.135 V`
  - entry tax-adjusted FDV `362.478804 万 USD`
  - board weighted cost `380.642784 万 USD`

## Control Findings

- TDS did not trigger under `50,000 V+` thresholds. This is expected because TDS max whale-board spent was only around `29,822 V`.
- ISC early 10-minute sample did trigger under low thresholds like `10,000 V`, but the early-window mark-to-market was strongly negative. This supports keeping the default threshold away from very low values.
- The strategy should be scoped to recognized 98-minute / Robotic style launches first. TDS-style launches should not share the same auto-buy policy.

## Current Recommendation

Do not ship automatic buying yet.

Recommended next simulation preset:

```text
launch profile: 98-minute / Robotic only
boardSpentV >= 100,000
buyTaxRate <= 92
estimatedFdvWanUsdWithTax <= boardCostWanUsd
buy size = 50 VIRTUAL
normal cooldown = 60s
burst rule = 2 buys within 120s -> 600s cooldown
max project spend = 300 VIRTUAL
min cost rows = 10
min whale rows = 10
```

Reason:

- It matched the user's baseline idea.
- It was profitable on high-resolution SR.
- It avoids the lower-confidence `50,000 V` early-entry path.
- It keeps position sizing small while we collect more 98-minute launch samples.

Next step before live trading:

- Add a dry-run signal emitter that logs would-buy events in realtime, without sending transactions.
- Keep it scoped to 98-minute / Robotic projects.
- Require at least one more real project dry-run before any hot wallet execution path.
