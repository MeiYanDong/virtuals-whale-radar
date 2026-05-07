# Chainstack Full-window Test - 2026-05-07

## Scope

- Server path: `/opt/virtuals-whale-radar`
- RPC: Chainstack Base mainnet HTTP/WSS from server env files
- Endpoint token recorded in Git/docs: no
- Production DB touched: no
- Replay DB: isolated SQLite under `data/replay-chainstack-full-20260507/`
- Test time: 2026-05-07 15:51-16:10 CST

## Test Matrix

| Test | Project | Virtuals ID | Launch / tax profile | Result |
| --- | --- | ---: | --- | --- |
| Full-window replay | TDS | `72562` | Unicorn / `antiSniperTaxType=1` / 60s-style tax | passed |
| Full-window replay | SR | `70972` | Robotic / `antiSniperTaxType=2` | passed |
| Fault injection | missing Chainstack env | - | env check | expected `red` |
| Fault injection | bad HTTP/WSS endpoint | - | RPC smoke | expected `red` |
| Production health | live services | - | post-test runtime | passed |

## TDS Result

- Summary: `data/replay-chainstack-full-20260507/tds_chainstack_full_20260507-20260507T075130Z-summary.json`
- Window: 99 minutes, 20x speed
- Blocks: `45383228` to `45386197`
- Transactions: `504`
- Parsed events: `128`
- Inserted events: `128`
- Samples: `144`
- Historical `eth_call`: supported
- `logErrors`: `[]`
- Final `priceLatencyMs`: `70`
- Final `estimatedFdvWanUsdWithTax`: `8.381059987691003414`
- Final `sumTaxV`: `30.720000000000000000`
- Final `boardSpentV`: `29821.721714`
- Final `boardCostWanUsd`: `7.220430`
- Final `costPosition`: `5/20`
- Final `vCostPosition`: `7391/29822`

## SR Result

- Summary: `data/replay-chainstack-full-20260507/sr_chainstack_full_20260507-20260507T080007Z-summary.json`
- Window: 99 minutes, 20x speed
- Blocks: `44629933` to `44632903`
- Transactions: `753`
- Parsed events: `602`
- Inserted events: `602`
- Samples: `144`
- Historical `eth_call`: supported
- `logErrors`: `[]`
- Final `priceLatencyMs`: `79`
- Final `estimatedFdvWanUsdWithTax`: `523.023504340542854554`
- Final `sumTaxV`: `448339.638338892498857051`
- Final `boardSpentV`: `314740.058350`
- Final `boardCostWanUsd`: `445.419458`
- Final `costPosition`: `18/19`
- Final `vCostPosition`: `275170/314740`

## Fault Injection

The fault-injection checks were run with temporary environment overrides only. They did not modify `/etc/virtuals-whale-radar/*.env`, production services, or the production DB.

- Missing env report: `data/audits/chainstack-suite-20260507-fault-missing-env.json`
- Bad RPC report: `data/audits/chainstack-suite-20260507-fault-bad-rpc.json`
- Missing env result: expected `status=red`
- Bad endpoint result: expected `status=red`; HTTP `eth_blockNumber` and WSS `eth_blockNumber` both failed as intended
- Follow-up fix: `run_chainstack_test_suite.py` now reports both missing HTTP and WSS env names when both are absent

## Production Health After Tests

- `vwr-signalhub.service`: active
- `vwr@writer.service`: active
- `vwr@realtime.service`: active
- `vwr@backfill.service`: active
- SignalHub `/healthz`: `status=ok`
- Main `/health`: `ok=true`
- Runtime paused: `false`
- Queue size: `0`
- Pending tx: `0`
- WSS connected: `true`

## Verdict

Passed for the current known replay risk set:

- Chainstack full-window logs / receipt / historical pool reserve reads worked for TDS and SR.
- Robotic Launch and Unicorn / 60s-style tax replay paths both produced continuous samples.
- `含税估算 FDV` and `打新成本位` were populated through the full replay windows.
- Fault-injection checks fail closed for missing or unreachable Chainstack endpoints.

Residual risk:

- This is still historical replay plus live health, not the next real live launch window.
- The next real project still needs live observation for WSS subscription stability and actual SignalHub project ingestion.
