# ISC Native Replay Test - 2026-04-30

## Goal

Use the closest-to-production replay path to test whether `含税估算 FDV（万 USD）` and `打新成本位` refresh and calculate correctly.

Replay target:

- Project: ISC / Isaac Protocol
- Virtuals ID: `72752`
- Window: first `10` launch minutes
- Speed: `5x`
- Real duration: about `2` minutes
- RPC: ANKR via `ANKR_BASE_HTTP_RPC_URL`
- Isolation: temporary SQLite DB under `data/replay/`

## Command

Run from the server so the ANKR key stays inside `/etc/virtuals-whale-radar/rpc.env`:

```bash
cd /opt/virtuals-whale-radar
set -a
. /etc/virtuals-whale-radar/rpc.env
set +a
./.venv/bin/python scripts/ops/native_launch_replay.py \
  --duration-minutes 10 \
  --speed 5 \
  --sample-interval-sec 1 \
  --tick-sec 0.2
```

The script defaults to `ANKR_BASE_HTTP_RPC_URL` when that environment variable is present.

## Native Path

The replay uses:

```text
eth_getLogs / receipt / block timestamp
-> parse_receipt_for_launch
-> Storage.flush_events
-> minute_agg / leaderboard / project_stats
-> project overview logic
-> historical pool getReserves
-> tax-adjusted market payload
```

Only two things are simulated:

- clock: original ISC launch time is replayed at `5x`
- database: writes go to an isolated temporary DB

## Result

Output files:

- Summary: `/opt/virtuals-whale-radar/data/replay/isc_replay-20260430T120839Z-summary.json`
- Samples: `/opt/virtuals-whale-radar/data/replay/isc_replay-20260430T120839Z-samples.jsonl`
- Replay DB: `/opt/virtuals-whale-radar/data/replay/isc_replay-20260430T120839Z.db`

Observed:

- `eth_getLogs`: success, no split errors
- historical `eth_call(getReserves)`: supported
- discovered tx: `89`
- parsed events: `74`
- inserted events: `74`
- samples: `115`
- formula errors for `estimatedFdvWanUsdWithTax`: `0`
- market latency: min `38ms`, average `61.2ms`, p50 `48ms`, max `284ms`
- final DB counts:
  - `events = 74`
  - `minute_agg = 8`
  - `leaderboard = 45`
  - `project_stats = 1`

Final sample:

```text
price source: historical_pool_reserves
token price: 0.000132709810150695 USD
live FDV: 132,709.81015069477 USD
tax rate: 89%
tax-adjusted FDV: 120.645281955177 万 USD
tax collected: 45,629.737811322 V
whale rows: 20
cost rows: 19
excluded rows: 1
board V: 43,919.552511
board cost: 149.509796 万 USD
cost position: 1/19
V cost position: 0/43,920
```

## Notes

- The first parsed event appears at simulated `1777473067`, about `63s` after launch.
- The first usable cost-position row appears at simulated `1777473221`.
- The known ISC top wallet `0x81f7ca6af86d1ca6335e44a2c28bc88807491415` is detected as the excluded early low-cost/team-like row in this replay, so cost metrics use `19` included rows instead of all `20` displayed whale rows.
- During the replay, `costPosition` briefly moved to `2/19` when one wallet cost fell below current tax-adjusted FDV, then returned to `1/19` as tax-adjusted FDV dropped with tax decay.

## Verdict

The replay passed for the tested 10-minute ISC window:

- tax-adjusted FDV formula matches backend samples
- historical market data used the native pool reserve path
- cost-position metrics changed as events entered the leaderboard
- team-like early buy exclusion affected cost metrics without deleting the raw leaderboard row
