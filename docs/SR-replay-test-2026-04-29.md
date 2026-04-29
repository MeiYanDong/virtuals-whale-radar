# SR Replay Test - 2026-04-29

## 1. 测试目标

在不修改生产数据库的前提下，把新 `SR` 当成一次历史正式发射来重跑：

- 复用当前生产代码和解析器
- 用隔离数据库模拟 `SR` 发射窗口
- 重新扫描历史交易
- 验证 `tax-only` 买单能被解析
- 重建 `events / minute_agg / minute_buyers / leaderboard / wallet_positions / project_stats`
- 与当前生产 baseline 对账

## 2. 项目范围

- 项目：`SR`
- `SignalHub project_id`：`70972`
- Token：`0x10c56f005a379f8eafc88ff5c3f40d30f0031ac9`
- 内盘：`0x745c62e112435afcbd942504002d1ddd305ce0db`
- 原始发射时间：`2026-04-13T03:00:13Z`
- 本次发射扫描窗口：
  - `start_ts = 1776049200`
  - `end_ts = 1776055173`
  - `from_block = 44629927`
  - `to_block = 44632913`

## 3. 隔离环境

- 服务器：阿里云轻量应用服务器
- 生产路径：`/opt/virtuals-whale-radar`
- 隔离目录：`/opt/virtuals-whale-radar/output/sr-replay-test-20260429-154656`
- 主库快照：`virtuals_v11.production-snapshot.db`
- 隔离主库：`virtuals_v11.work.db`
- 隔离总线库：`virtuals_bus.work.db`
- `SignalHub` 快照：`signalhub.production-snapshot.db`

快照方式使用 `sqlite3 .backup`，不要直接 `cp` 正在 WAL 模式运行的 SQLite 数据库。直接复制时本次曾遇到 `database disk image is malformed`，说明热库复制必须走一致性备份。

## 4. Baseline

当前生产 baseline：

| 表/指标 | 数量 |
| --- | ---: |
| `events` | 602 |
| `event_distinct_txs` | 602 |
| `minute_agg` | 87 |
| `minute_buyers` | 588 |
| `leaderboard` | 185 |
| `wallet_positions` | 2 |
| `project_stats` | 1 |
| `scanned_backfill_txs` | 374 |
| `dead_letters_like_sr` | 0 |

金额口径：

| 指标 | 数值 |
| --- | ---: |
| `total_spent_v_est` | 617721.103735 |
| `total_tax_v` | 448339.6383388925 |
| `total_fee_v` | 0 |
| `total_token_bought` | 484210484.27443874 |

## 5. 执行过程

### 5.1 自动 scan

- RPC：`https://base-rpc.publicnode.com`
- 初始块大小：`50`
- 总 chunk：`60`
- 结果：
  - `events = 533`
  - `event_distinct_txs = 533`
  - `minute_agg = 84`
  - `minute_buyers = 522`
  - `leaderboard = 179`
  - `wallet_positions = 2`
  - `dead_letters_like_sr = 0`
- 与 baseline 差异：
  - 少 `69` 笔 tx
  - 无多余 tx
  - 无 dead letter

判断：自动日志扫描可以重建大部分 SR 数据，但不能完整复原当前生产 baseline。

### 5.2 缺口 tx 强制 replay

对自动 scan 缺失的 `69` 笔 tx 做强制 replay 后：

- `events = 595`
- 仍缺 `7` 笔 tx
- `top20` 顺序已经与 baseline 一致
- 无 dead letter

### 5.3 定点多 RPC 复核

对剩余 `7` 笔 tx 做定点重试，结果全部补入：

- `final_missing_count = 0`
- 这 `7` 笔 receipt 均存在
- 交易与 `SR` launch config 相关
- 换节点或重试后可正常解析入库

判断：最后缺口不是解析器无法处理，而是 RPC / 重试路径稳定性问题。

## 6. 最终对账

最终隔离库与 baseline 对账：

| 表/指标 | baseline | replay | diff |
| --- | ---: | ---: | ---: |
| `events` | 602 | 602 | 0 |
| `event_distinct_txs` | 602 | 602 | 0 |
| `minute_agg` | 87 | 87 | 0 |
| `minute_buyers` | 588 | 588 | 0 |
| `leaderboard` | 185 | 185 | 0 |
| `wallet_positions` | 2 | 2 | 0 |
| `project_stats` | 1 | 1 | 0 |
| `dead_letters_like_sr` | 0 | 0 | 0 |

额外说明：

- `scanned_backfill_txs` 从 baseline 的 `374` 变成 replay 的 `754`，这是测试过程把自动 scan 候选和缺口 tx 都标记为 scanned 导致的，不影响聚合结果。
- `top20_same_order = true`
- `missing_tx_count = 0`
- `extra_tx_count = 0`

## 7. 产物

- `baseline.json`
- `baseline_tx_hashes.txt`
- `baseline_top20.csv`
- `work_after_clean.json`
- `scan_comparison.json`
- `replay_progress.json`
- `targeted_missing_replay.json`
- `replay_result.after-targeted.json`
- `comparison.after-targeted.json`
- `replay_top20.after-targeted.csv`

目录：

`/opt/virtuals-whale-radar/output/sr-replay-test-20260429-154656`

## 8. RPC 复测与工具化

> 2026-04-29 晚间追加 Ankr 充值后全链路复测，当前生产推荐已改为：
>
> - 主路径：`Ankr logs + Ankr receipt + Ankr block`
> - 默认并发：`16`
> - Base official 只保留为 logs 备用
> - Alchemy 免费 key 只保留为小窗口 / 低并发备用
> - Chainstack 当前 plan 不再作为 Base 历史 logs / block 路径
>
> 下方 Chainstack / mainnet.base.org 结论保留为 Ankr 充值前的历史记录。

在用户指出“为什么不用我们自己的 RPC”后，对服务器上的可用 RPC 做了补充测速：

- Chainstack 自有 RPC：`eth_blockNumber` / `eth_getTransactionReceipt` 最快，约 `65-75ms`，适合 receipt 读取和解析。
- 当前 Chainstack plan 对 `SR` 历史 `eth_getLogs` 窗口返回 archive / debug / trace plan 限制，不适合作为本次历史日志发现入口。
- `https://base-rpc.publicnode.com` 可用但慢，`50` block 日志查询约 `11-13s`，完整窗口容易超时。
- `https://mainnet.base.org` 在本次测试中最适合历史日志发现，`SR` 完整窗口日志查询约 `505ms`。
- `https://base.llamarpc.com` 在本次测试中返回异常，不应放在优先路径。

因此当时推荐分工：

- 日志发现：优先 `https://mainnet.base.org`
- 历史 block timestamp：优先 `https://mainnet.base.org`
- receipt / token metadata：优先 Chainstack 自有 RPC
- 公开 RPC：只作为 fallback

已新增正式运维工具：

- 本地与服务器路径：`scripts/ops/replay_project_txs.py`
- 支持按 `tx hash` 重放，也支持按 `from_block / to_block` 做日志发现
- 支持 `--logs-rpc-url` / `--block-rpc-url` / `--receipt-rpc-url` 分离，避免用慢公共 RPC 拉 receipt，也避免用当前 Chainstack plan 查询历史 block
- 已新增项目完整性审计工具：`scripts/ops/audit_project_window.py`
  - 支持按项目窗口重新发现候选 tx
  - 对比 `events / scanned_backfill_txs / dead_letters`
  - 输出 `green / red / observed` 状态
  - 对未解析、未标记扫描的候选 tx 生成 replay 修复命令
- 修正前服务器 smoke test 中，1 笔历史 tx 会因为 3 条 Chainstack 依次命中 archive plan 限制而耗时约 `25s`
- 修正后服务器 smoke test 已在隔离 SR work DB 副本上通过：清空 `SR` 后重放 `1` 笔 tx，`before_events = 0`，`after_events = 1`，耗时约 `1s`，生产库未被修改

服务器配置已把 `BACKFILL_PUBLIC_HTTP_RPC_URLS` 调整为：

1. `https://mainnet.base.org`
2. `https://base-rpc.publicnode.com`
3. `https://base.llamarpc.com`

## 9. 结论

本次隔离重跑通过。

已经确认：

- 当前解析器可以处理新 `SR` 的 `tax-only` 买入结构。
- 从干净隔离库重建后，核心聚合表可与当前生产 baseline 完全对齐。
- 单纯依赖慢公共 RPC 自动日志扫描时，可能因为 RPC / 日志覆盖 / 重试稳定性少扫部分 tx。
- 已正式化“按 tx hash 强制 replay 缺口”的运维工具。
- 历史 replay 要把 logs / block timestamp / receipt 三类 RPC 分开选路。
- SQLite 生产库热备必须使用 `.backup`，不能直接复制主库文件。

## 10. 生产删除后真实重建验证

2026-04-29 晚间进一步在生产库执行了破坏性验证：先备份，再删除线上 `SR` 派生数据，然后由生产 `scan_jobs` 工作流重新扫描完整发射窗口。

执行边界：

- 服务器：阿里云轻量应用服务器
- 生产路径：`/opt/virtuals-whale-radar`
- 产物目录：`/opt/virtuals-whale-radar/output/sr-production-reset-20260429-215556`
- 备份方式：`sqlite3 .backup`
- 备份文件：
  - `virtuals_v11.before-delete.db`
  - `virtuals_bus.before-delete.db`
- 删除范围仅限 `project = 'SR'` 的派生数据：
  - `events`
  - `minute_agg`
  - `minute_buyers`
  - `leaderboard`
  - `wallet_positions`
  - `project_stats`
  - `scanned_backfill_txs`
- 未删除：
  - `managed_projects`
  - `launch_configs`
  - 用户、积分、权限、SignalHub 数据
  - `dead_letters`

生产 scan job：

- job id：`sr2200460182`
- 时间窗：`1776049200 -> 1776055173`
- 区块窗：`44629927 -> 44632913`
- chunk：`3`
- scanned tx：`754`
- processed tx：`754`
- parsed delta：`602`

最终结果：

| 指标 | 结果 |
| --- | ---: |
| `events` | 602 |
| `event_distinct_txs` | 602 |
| `minute_agg` | 87 |
| `minute_buyers` | 588 |
| `leaderboard` | 185 |
| `wallet_positions` | 2 |
| `project_stats` | 1 |
| `scanned_backfill_txs` | 754 |

完整性审计：

- `audit_status = green`
- `candidate_txs = 754`
- `covered_candidates = 754`
- `candidate_with_event = 602`
- `scanned_without_event = 152`
- `repair_candidates = 0`
- `unresolved_dead = 0`
- `top20_same = true`

健康检查：

- `vwr@writer / vwr@realtime / vwr@backfill / vwr-signalhub / nginx` 全部 `active`
- `/health` 返回 `ok = true`
- `/healthz` 返回 `status = ok`
- `queue_size = 0`
- `pending_tx = 0`
- `runtime_paused = false`

结论：

- 当前生产 scan job 工作流可以在删除 `SR` 派生数据后，独立从链上重建完整数据。
- 本次没有触发 repair replay，说明 Ankr 主路径在 `SR` 完整窗口上足以支撑真实重建。
- `scanned_backfill_txs` 从历史 baseline 的 `374` 增加到 `754` 是预期结果：本次生产重建把所有候选 tx 都标记为已扫描，不影响 `events` 和聚合结果。
