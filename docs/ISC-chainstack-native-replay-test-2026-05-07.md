# ISC Chainstack Native Replay Test - 2026-05-07

## Goal

Use the closest-to-production replay path to verify whether the current Chainstack-first runtime can support a realistic launch-window simulation for `含税估算 FDV（万 USD）` and `打新成本位`.

Replay target:

- Project: ISC / Isaac Protocol
- Virtuals ID: `72752`
- Window: first `10` launch minutes
- Speed: `5x`
- Real duration: about `2` minutes
- Primary RPC under test: Chainstack Base mainnet HTTPS
- Comparison RPC: ANKR Base HTTPS
- Isolation: temporary SQLite DB under server `data/replay-*`

No production DB writes were made. RPC endpoint tokens were read from `/etc/virtuals-whale-radar/rpc.env` and are intentionally not recorded here.

## Native Path

The replay uses the same backend path that matters for production launch monitoring:

```text
eth_getLogs
-> eth_getTransactionReceipt
-> historical block timestamp
-> parse_receipt_for_launch
-> isolated SQLite Storage.flush_events
-> minute_agg / leaderboard / project_stats
-> project overview logic
-> historical pool getReserves
-> tax-adjusted market payload
-> cost-position metrics
```

Only two things are simulated:

- clock: the original ISC launch window is replayed at `5x`
- database: writes go to an isolated replay DB, not the production DB

## Chainstack Result

Output files:

- Summary: `/opt/virtuals-whale-radar/data/replay-chainstack-20260507/isc_chainstack_replay-20260507T063929Z-summary.json`
- Samples: `/opt/virtuals-whale-radar/data/replay-chainstack-20260507/isc_chainstack_replay-20260507T063929Z-samples.jsonl`
- Replay DB: `/opt/virtuals-whale-radar/data/replay-chainstack-20260507/isc_chainstack_replay-20260507T063929Z.db`

Observed:

- discovered tx: `89`
- parsed events: `74`
- inserted events: `74`
- samples: `112`
- `historicalEthCallSupported`: `true`
- `logSplits`: `[]`
- `logErrors`: `[]`
- market latency: min `63ms`, p50 `76ms`, p95 `417ms`, max `782ms`

Final sample:

```text
price source: historical_pool_reserves
price block: 45342128
token price: 0.000171772602150356 USD
live FDV: 171,772.602150356 USD
tax rate: 89%
tax-adjusted FDV: 156.156911 万 USD
tax collected: 45,629.737811322 V
whale rows: 20
cost rows: 19
excluded rows: 1
board V: 43,919.552511
board cost: 193.517620 万 USD
cost position: 1/19
V cost position: 0/43,920
```

## ANKR Comparison

To rule out provider-specific replay drift, the same current code was run again with ANKR as the explicit logs and receipt RPC.

Output files:

- Summary: `/opt/virtuals-whale-radar/data/replay-ankr-compare-20260507/isc_ankr_compare-20260507T065935Z-summary.json`
- Samples: `/opt/virtuals-whale-radar/data/replay-ankr-compare-20260507/isc_ankr_compare-20260507T065935Z-samples.jsonl`
- Replay DB: `/opt/virtuals-whale-radar/data/replay-ankr-compare-20260507/isc_ankr_compare-20260507T065935Z.db`

Observed:

- discovered tx: `89`
- parsed events: `74`
- inserted events: `74`
- samples: `116`
- `historicalEthCallSupported`: `true`
- `logSplits`: `[]`
- `logErrors`: `[]`

Final sample:

```text
price source: historical_pool_reserves
price block: 45342128
token price: 0.000177225742227418 USD
live FDV: 177,225.742227418 USD
tax rate: 89%
tax-adjusted FDV: 161.114311 万 USD
tax collected: 45,629.737811322 V
whale rows: 20
cost rows: 19
excluded rows: 1
board V: 43,919.552511
board cost: 199.661084 万 USD
cost position: 1/19
V cost position: 0/43,920
```

## Difference Explanation

The USD values above are not directly comparable because replay uses the current `VIRTUAL/USD` price read at replay startup while token pool reserves are read at historical ISC blocks.

Recorded `VIRTUAL/USD`:

- Chainstack replay startup: `0.903436156289014003`
- ANKR comparison startup: `0.932116887961305722`

After normalizing to V-native values, both providers match:

| Metric | Chainstack | ANKR | Difference |
| --- | ---: | ---: | ---: |
| final token price in V | `0.00019013253006823986` | `0.00019013253006824080` | effectively `0` |
| final tax-adjusted FDV in V | `1,728,477.5460749118` | `1,728,477.5460749118` | effectively `0` |
| final board cost FDV in V | `2,142,017.6583910451` | `2,142,017.6651524029` | about `0.0000003%` |

This means the Chainstack and ANKR replay paths agree on the deterministic chain-derived data. The USD gap is caused by the live VIRTUAL/USD conversion point, not by `eth_getLogs`, receipt parsing, historical `eth_call`, or cost-position logic.

## Production Health After Replay

After the replay:

- `vwr-signalhub.service`: active
- `vwr@writer.service`: active
- `vwr@realtime.service`: active
- `vwr@backfill.service`: active
- SignalHub `/healthz`: ok
- Main `/health`: ok
- `runtimePaused`: false
- `ws_connected`: true

## Verdict

The simulated-real ISC replay passed for the tested `10` minute window:

- Chainstack can serve the complete replay path for this window: logs, receipts, block timestamps, and historical pool reserves.
- `含税估算 FDV` refreshed through the market path and followed the tax schedule.
- `打新成本位` refreshed as replayed events entered the leaderboard and preserved the team-like exclusion behavior.
- Provider comparison with ANKR confirms the deterministic V-native chain data matches.

Remaining production risk:

- This is still an isolated replay, not a real future live launch.
- The next real launch should still be observed end to end for Chainstack plan limits, websocket behavior, and frontend authenticated display.
