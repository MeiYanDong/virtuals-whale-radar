# Phase 053 Launch Execution Pipeline Plan

## 1. 目标

把 Phase 052 已验证的 `dynamic_25v_dip20_after1_flat10_no_cap` 策略，推进到完整执行链路：

```text
StrategyEvaluator
  -> BuyIntent
  -> OrderBuilder
  -> TxSimulator
  -> LocalSigner
  -> Broadcaster
  -> ReceiptVerifier
  -> ExecutionLedger
```

阶段目标不是立即自动实盘，而是逐层打通并测试每一层。任何一层没有证据通过，下一层不能启用。

## 2. 非目标

- 不直接在主程序里启用自动广播。
- 不把私钥写进代码、数据库、日志、JSON 报告或命令参数。
- 不绕过 `eth_call / allowance / balance / gas / nonce` 模拟检查。
- 不在没有手动确认和 burner wallet 的情况下做主网真实 canary。
- 不把历史回测收益当作真实交易收益承诺。

## 3. 当前采用策略

策略：`dynamic_25v_dip20_after1_flat10_no_cap`。

硬条件：
- `projectStatus == live`。
- `boardSpentV >= 5,000 V`。
- `whaleRows >= 20`。
- `costRows >= 5`。
- `buyTaxRate <= rule threshold`。
- `estimatedFdvWanUsdWithTax <= boardCostWanUsd`。
- 同一税率档位最多买一次。

买入数量：
- 默认 `25 VIRTUAL`。
- 若当前含税 FDV `<= 我方历史加权买入 FDV * 0.8`，买 `50 VIRTUAL`。

暂停规则：
- 某税率分钟买入后，如果下一税率分钟 FDV 相对上一买点变化 `<=10%`，跳过该税率档。
- 再下一个税率档重新计算。

## 4. 程序分层

### 4.1 StrategyEvaluator

输入：
- 当前项目 snapshot。
- 当前项目策略状态。

输出：
- `BuyIntent`。
- `pause`。
- `skip`。

必须记录：
- 触发来源：`pool_state_change / tax_tick / heartbeat`。
- 当前税率。
- 买入 V 数量。
- 含税 FDV。
- 榜单成本。
- 榜单 V。
- 暂停或跳过原因。

当前脚本：
- `scripts/ops/launch_execution_pipeline.py`
- `scripts/ops/test_launch_execution_pipeline.py`

### 4.2 OrderBuilder

职责：
- 把 `BuyIntent` 转成 unsigned transaction。

当前状态：
- 已完成直接买入 calldata 研究：`docs/phases/phase-053-virtuals-buy-calldata-research-2026-05-10.md`。
- 直接买入路由：`0x1a540088125d00dd3990f9da45ca0859af4d3b01`。
- 直接买入 selector：`0x706910ff`。
- 函数：`buy(uint256 amountIn_, address tokenAddress_, uint256 amountOutMin_, uint256 deadline_)`。
- `value=0`，VIRTUAL 走 ERC-20 transfer/allowance。
- 已实现标准 4 参数 calldata encoder 和显式参数 unsigned tx builder。
- 已完成历史样本 parity test：canonical 样本 exact parity，带尾部标签样本 canonical prefix parity。
- 已完成 spender trace：`docs/phases/phase-053-virtuals-buy-spender-trace-2026-05-10.md`。
- 直接买入入口 router 不等于 VIRTUAL spender；真实 spender 是 `0x02fe8ec3d9bbf7318eb54590bcc39198a8b47ded`。
- TxSimulator 已实现 `eth_call / estimateGas / balance / allowance / nonce / deadline` 只读检查。
- 真实 RPC probe 已验证检查链路可执行，历史地址当前因 balance 不足而 `green=false`，不允许签名。
- 已完成买入方式通用性审计：`docs/phases/phase-053-virtuals-buy-route-universality-audit-2026-05-10.md`。
- 本地 SR/ISC/TDS 共 240 个样本中，普通用户 direct buy 入口稳定为 router `0x1a540088125d00dd3990f9da45ca0859af4d3b01` + selector `0x706910ff`。
- 但它不是所有交易通用：团队/初始化交易使用同 router 但 selector `0x214013ca`；部分成交走 alternate/aggregator router `0x5ff137d4b0fdcd49dca30c7cf57e578a026d2789` + selector `0x1fad948c`。
- 已完成 order binding / `amountOutMin`：`docs/phases/phase-053-virtuals-order-binding-minout-2026-05-10.md`。
- 默认 launch 参数：`slippage_bps=5000`，`deadline_offset_sec=180`，`lp_fee_bps=30`。
- 执行层支持标准 `token0/token1` 池，也支持 Virtuals internal pool 的 reserve fallback。
- `TxSimulator` 已把 `amountOutMin > 0` 纳入绿灯检查。

下一步必须先完成：
- 准备 burner wallet 的只读地址检查，不接私钥。
- 设计 burner wallet secret 配置方式，并先做本地签名但不广播测试。

未完成 simulation green 前，OrderBuilder 不允许接入签名。

### 4.3 TxSimulator

职责：
- 在签名前模拟 unsigned transaction。

必须检查：
- [x] `eth_call` 不 revert。
- [x] VIRTUAL balance 足够。
- [x] allowance 足够，且 spender 必须是 `0x02fe8ec3d9bbf7318eb54590bcc39198a8b47ded`。
- [x] gas estimate 正常。
- [x] nonce 正常。
- [x] slippage 在允许范围内。
- [x] `amountOutMin > 0`。
- [x] deadline 合理。

模拟失败时：
- 不签名。
- 记录失败原因。
- 触发执行熔断或跳过该 intent。

### 4.4 LocalSigner

职责：
- 只签名 simulation green 的交易。

约束：
- 只能使用 burner wallet。
- 私钥只允许来自环境变量 `VWR_BURNER_PRIVATE_KEY`。
- 禁止打印私钥、raw private key、seed phrase。
- 禁止把私钥写入 SQLite、JSONL、Markdown、日志。

测试顺序：
- 构造 unsigned tx。
- 本地签名。
- 验证 raw tx 可 recover，from 地址正确。
- 不广播。

当前状态：
- 已实现 `LocalSigner`。
- 已接入 `eth-account==0.13.7`。
- 已完成本地 no-broadcast smoke test：`docs/phases/phase-053-local-signer-no-broadcast-2026-05-10.md`。
- 已用真实 burner 钱包做 no-broadcast 演练，签名后不广播。

### 4.5 Broadcaster

职责：
- 广播 signed raw transaction。

启用条件：
- OrderBuilder parity test 通过。
- TxSimulator 通过。
- LocalSigner 签名测试通过。
- Burner wallet 余额和授权已确认。
- 用户手动确认小额主网 canary。

默认：
- 广播功能关闭。
- 没有显式 allow flag 时必须拒绝发送。

当前状态：
- `launch_prewarm_executor.py` 已接入 `broadcast` 模式。
- 启动真实广播必须同时满足：
  - CLI：`--mode broadcast --enable-broadcast`。
  - 环境变量：`VWR_ENABLE_AUTO_BUY_BROADCAST=1`。
  - 独立交易 RPC：默认要求 `VWR_EXEC_HTTP_RPC_URL` 不与主采集 RPC 共用。
  - active fuse 为空。
  - 单笔上限、单项目上限、同一税率档未发过交易。
- ROO 当前上限：`--max-buy-v 50`、`--max-project-v 300`，匹配当前策略的 25V 基础买入、50V dip20 加倍买入和 300V 项目预算。
- 广播后写入 `broadcast_sent`；等待 receipt 时写入 `receipt_success / receipt_failed`，失败会触发执行熔断。
- `broadcast` 模式下，钱包 `balance / allowance` 不足只记录 `readiness_not_ready`，不触发 active fuse；如果未真实发出交易，执行器会回滚本次策略内存状态，避免资金稍后转入后被误判为“该税率档已买过”。
- 2026-05-11 核心链路审计修复：`launch_execution_ledger` 后续异常更新不再把已发送交易的 `trade_sent=1 / broadcast_enabled=1` 覆盖回 `0`，避免同税率档防重和项目上限统计失效。
- raw transaction 只在进程内用于 `eth_sendRawTransaction`，不写入日志、SQLite 或 JSONL。

### 4.6 ReceiptVerifier

职责：
- 等待 receipt。
- 判断成功/失败。
- 验证余额变化、token 到账、事件日志。

必须记录：
- tx hash。
- block number。
- gas used。
- status。
- revert reason 或失败分类。
- 交易后 token/VIRTUAL 余额变化。

### 4.7 ExecutionLedger

职责：
- 保存每次执行链路状态，支持审计和回放。

当前状态：
- 已新增 SQLite 表 `launch_execution_ledger`。
- 已新增 SQLite 表 `launch_execution_fuses`，独立记录自动买入执行熔断，不复用主采集 `runtime_paused`。
- 已新增 `Storage.upsert_launch_execution_record(...)`、`get_launch_execution_record(...)`、`list_launch_execution_records(...)`。
- 已新增 `Storage.trigger_launch_execution_fuse(...)`、`get_active_launch_execution_fuse(...)`、`clear_launch_execution_fuse(...)`、`list_launch_execution_fuses(...)`。
- 已新增运维脚本 `scripts/ops/launch_execution_fuse.py`，支持 list active fuse 和 clear fuse。
- `live_strategy_dry_run.py` 会把 `would_buy` 和 `pause` 写入执行账本，仍保持 `tradeSent=false`、`broadcastEnabled=false`。
- `prewarmed_buy_canary.py` 已支持可选 `--ledger-intent-id`，可把 simulation、sign、broadcast、receipt 阶段摘要写入同一条执行账本。
- `prewarmed_buy_canary.py` 已接入 active fuse 检查：同项目/策略/规则存在 active fuse 时，`--broadcast` 会在发送前被阻断。
- simulation/sign/broadcast/receipt/canary 异常会触发执行熔断，熔断记录包含 project、strategy、rule、stage、reason、source intent 和摘要 details。
- 生产预热执行器已接入 broadcast/receipt 阶段账本写入与失败熔断。
- 账本不保存 raw transaction 和私钥；签名阶段只保存 `signed_tx_hash`，广播阶段只保存 `broadcast_tx_hash`，receipt 阶段只保存状态、区块、gas 和余额变化摘要。
- 当前仍未启用生产自动交易；ROO 生产服务仍是 `simulate`，canary/自动执行都必须显式广播门禁才会发送。

字段覆盖：
- `intent_id`。
- project id/name、SignalHub project id。
- strategy version、rule name、mode。
- status、action、decision reason。
- sample index、snapshot timestamp、tax rate。
- buy size、entry FDV、board spent、board cost。
- trigger types、snapshot JSON、intent JSON。
- simulation JSON、signed tx hash、broadcast tx hash、receipt JSON。
- failure stage / reason。
- `trade_sent`、`broadcast_enabled`。
- created/updated timestamp。

熔断边界：
- 熔断只影响自动买入执行链路，不停止 writer/realtime/backfill 采集。
- 灰度执行器进入真实广播前必须先查询 active fuse。
- active fuse 必须手动 clear，不能由下一次成功模拟自动解除。
- 本地已验证：no-broadcast TDS simulation failure 会落 active fuse；同项目/策略/规则 `--broadcast` 会在发送前被阻断；运维脚本可 list/clear active fuse。

### 4.8 Latency Model

第一买入的延迟指标必须拆开：

- `submit latency`：`tax_tick -> eth_sendRawTransaction ACK`。
- `receipt latency`：`eth_sendRawTransaction -> receipt`。

第一买入只考核 `submit latency`。receipt 受 Base 出块时间影响，不能作为抢第一买点的执行标准。

当前本地 Chainstack 只读延迟探针：

- 脚本：`scripts/ops/launch_latency_probe.py`。
- 输出：`data/backtests/launch-latency-probe-chainstack-rrr-20260510.json`。
- 样本：RRR 当前 undergrad direct-buy token。
- 中位 `eth_blockNumber`：`277.9ms`。
- 中位 `coldPrepareMs`：`1278.3ms`。
- 中位 `hotPathLocalMs`：`12.8ms`。
- 最大 `coldPrepareMs`：`3248.9ms`，说明冷路径存在 RPC outlier，不能作为生产第一买入主路径。

生产第一买入必须使用预热路径：

- 税率 tick 由 `launchedAt + antiSniperTaxType` 预计算。
- 榜单、FDV、成本位持续维护在本地内存。
- nonce、fee、gas、allowance、balance 提前检查。
- 候选交易提前构造或预签。
- tick 到达时只做本地条件判断和广播。

目标：

- `tax_tick -> send ACK < 2s`。
- 理想路径 `< 1s`。
- receipt 单独记录，不用于判断是否满足第一买入速度。

### 4.9 RPC Isolation

采集 RPC 和自动买入 RPC 必须分层处理。

当前生产主流程已经长期占用 RPC：
- `realtime` 使用 WSS 监听新区块和交易。
- `backfill` 使用 HTTPS 做 `eth_getLogs`、历史区块时间、receipt 回扫。
- `writer` / API market path 会读取池子储备、VIRTUAL/USD、税率证据等实时数据。

自动买入链路不能默认假设这些 RPC 负载总是空闲。尤其在发射窗口内，前端 250ms 刷新、回扫补数据、税率 tick、策略判断、交易模拟和广播可能同时发生。如果自动买入与采集共用同一个 Chainstack endpoint，可能出现：
- RPC 排队导致 `eth_call / estimateGas / eth_sendRawTransaction` 延迟抬高；
- `eth_getLogs` 回扫与交易模拟争抢同一个 provider 额度；
- provider transient / quota 错误触发冷却，影响本应独立的交易路径；
- 采集链路为了完整性重试，反过来拖慢第一笔买入提交。

因此 RPC 策略按阶段区分：

- **实时 dry-run emitter**：默认不广播，可以使用主项目现有 RPC，但必须低频、按项目白名单运行，并记录 `rpcSharedWithMain`。dry-run 的目标是验证策略事件，不追求真实交易提交延迟。
- **预热交易服务**：必须支持独立 `VWR_EXEC_HTTP_RPC_URL`。该 RPC 只用于 `balance / allowance / nonce / fee / eth_call / estimateGas / eth_sendRawTransaction`，不承担历史 `eth_getLogs`。
- **真实自动买入**：优先使用独立交易 RPC；如果没有独立 RPC，服务只能进入 dry-run 或 armed-no-broadcast，不允许自动广播。

最低要求：
- 交易 RPC 与 backfill/logs RPC 分离。
- 交易 RPC 在 tick 前完成 nonce、fee、gas、allowance、balance 预检查。
- 触发时只允许走热路径广播。
- 所有日志必须脱敏 RPC token。
- 任意 RPC 异常必须记录并熔断当前自动执行，不影响主采集服务。

真实 canary 结果：

- 冷路径 `0.001 VIRTUAL -> RRR`：
  - tx：`0xa9deb7b59e365d6c0d961e7deef2a58df1a7dc972c2d276505d4d34ac5336f5b`。
  - `sendRawMs=438.6ms`。
  - `totalToSendAckMs=2644.1ms`。
  - receipt `status=1`，实际花费 `0.001 VIRTUAL`。
  - 结论：冷路径不满足 `<2s`，因为把读余额、报价、模拟、费用、签名放进了触发后路径。
- 热路径 `0.001 VIRTUAL -> RRR`：
  - tx：`0xb3542bf282ed76812534681baee3c5fe791031f300f4bed38a95aca4681c62bb`。
  - 预热耗时 `2216.5ms`，不计入 tax tick 后执行路径。
  - `triggerToSendAckMs=450.6ms`。
  - receipt `status=1`，实际花费 `0.001 VIRTUAL`。
  - 结论：预热路径满足 `<2s`，当前实测低于 `0.5s`。

工程化迭代：

- 新增 `scripts/ops/prewarmed_buy_canary.py`。
- 该脚本把预热和触发广播拆成两段：
  - 预热段：余额/授权读取、池子报价绑定、simulation、fee、gas、nonce、签名。
  - 触发段：只执行 `eth_sendRawTransaction`。
- 默认不广播；必须传 `--broadcast` 才会发送真实交易。
- 已验证当前 allowance 不足时 dry-run 会停在 simulation 阶段：`broadcasted=false`、`tradeSent=false`。
- `approve_virtual_spender.py` 已改为 receipt 后轮询确认 allowance，避免授权成功但即时读数 stale 导致误判。
- `approve_virtual_spender.py`、`approve_erc20_spender.py` 和 `tx_simulator_probe.py` 已改为优先使用独立 `VWR_EXEC_HTTP_RPC_URL`，并输出 `rpcSharedWithMain`，避免发射前预检误走主采集 RPC。
- `scripts/ops/execution_rpc.py` 已成为统一 execution RPC 解析入口；买入 canary、预热买入 canary、卖出、授权、readiness、latency probe、local signer probe 均记录 `rpcSharedWithMain / executionRpcSource`。
- 真实广播默认要求独立 `VWR_EXEC_HTTP_RPC_URL`。共享主采集 RPC 时，买入、卖出、授权和生产预热执行器会 fail-closed；只有显式 `--allow-shared-rpc-broadcast` 才允许临时绕过。
- `sell_virtuals_token.py` 输出已修复：`broadcastRequested` 真实反映 `--broadcast`，receipt 输出包含 `receiptOk / reason`，避免 no-broadcast 或失败 receipt 被误读成成功卖出。
- `approve_virtual_spender.py` 与 `approve_erc20_spender.py` 支持 `--skip-sign`，可在没有私钥文件时只读验证 approve 的 `eth_call / estimateGas / nonce / fee`，不签名、不广播。
- ERC-20 授权不要求当前 VIRTUAL 余额足够；授权交易只要求 burner 有 Base ETH 付 gas，后续可转出的 VIRTUAL 仍受 `min(balance, allowance)` 限制。
- 新增 `scripts/ops/launch_prewarm_executor.py`。
- 该脚本把实时策略判断和预热链路接起来：
  - 复用 `live_strategy_dry_run.py` 的项目取样、触发源判断和执行账本 intent 生成。
  - `simulate` 模式：BuyIntent 后执行订单绑定和 TxSimulator，不读取私钥、不签名、不广播。
  - `sign-ready` 模式：simulation green 后补 fee/gas/nonce 并本地签名，但不打印、不保存 raw transaction，也不广播。
  - 进入预热前先检查 active fuse；存在 active fuse 时阻断当前 intent。
  - `simulate` 模式下余额/授权不足记录为 `readiness_not_ready`，不触发 active fuse。
  - `sign-ready` 模式下 simulation/sign/prewarm 异常会写入执行账本并触发 `launch_execution_fuses`。
- 本地 TDS 烟测已验证：项目 ended 时只记录 `state_change/not_live`，不会产生买入、签名或广播。

Canary 退出：

- 已确认 direct sell selector：`sell(uint256,address,uint256,uint256)` / `0xb233e056`。
- 新增 `scripts/ops/approve_erc20_spender.py`，用于任意 ERC-20 精确授权。
- 新增 `scripts/ops/sell_virtuals_token.py`，用于将 Virtuals launch token 卖回 VIRTUAL。
- 本轮 canary 买入的 `TDS / RRR / AURA / ASDSDA` 已全部卖回 VIRTUAL。
- 卖回合计收到 `3.9223602 VIRTUAL`。
- 清仓后四个 token 余额均为 `0`，对 router/spender 的 allowance 均为 `0`。
- 最终 burner VIRTUAL 余额：`12.587713615542899411`。

## 5. 测试顺序

### Stage 1：离线策略 dry-run

- 用 SR/ISC event-level samples 跑 `BuyIntent`。
- 验证 `tradeSent=false`。
- 验证暂停点、买点、投入和收益与 Phase 052 报告一致。

已完成本地 smoke：
- SR `tax<=95`：`5` 个 BuyIntent，`2` 个暂停，`125V`，`tradeSent=false`。
- ISC `tax<=89`：`14` 个 BuyIntent，`14` 个暂停，`350V`，`tradeSent=false`。

### Stage 2：实时 dry-run emitter

- 接入主程序实时 snapshot。
- 只写 would-buy，不构造交易。
- 记录 trigger source 和完整 snapshot。
- tax-end 后回填表现。
- 作为独立 systemd 服务运行，不并入 `vwr@writer/realtime/backfill`。
- dry-run 阶段不需要私钥，不读取 `VWR_BURNER_PRIVATE_KEY`。
- 若未配置 `VWR_EXEC_HTTP_RPC_URL`，必须在日志中标记与主流程共用 RPC，仅用于策略观察。

ROO 部署状态：
- 服务：`vwr-launch-dryrun@ROO.service`。
- 输出：`data/execution/live-strategy-dry-run-ROO.jsonl`。
- 当前状态：只读 dry-run，`tradeSent=false`，`broadcastEnabled=false`。
- 当前 RPC：按当前决策使用 Chainstack Base endpoint。
- 当前 execution RPC 选型：独立 Chainstack Base Global node `virtuals-whale-radar-execution` / `ND-554-355-391`。
- 当前主流程 Chainstack endpoint hash 为 `481fbd2573aa`，execution Chainstack endpoint hash 为 `493d6968fc13`，二者已分离。
- 最新 ROO dry-run 启动日志必须显示 `rpcSharedWithMain=false`。
- 2026-05-11 远端轻量执行 RPC 基准：
  - execution/Ankr：`25/25` 成功，overall p50 `205.3ms`、p90 `225.2ms`、max `351.4ms`。
  - Chainstack：`25/25` 成功，overall p50 `266.7ms`、p90 `576.7ms`、max `851.4ms`。
  - Alchemy：此前测试已出现 monthly capacity limit，不纳入 execution。
- 2026-05-11 创建独立 Chainstack execution node 后复测：
  - execution/Chainstack dedicated：`50/50` 成功，overall p50 `283.3ms`、p90 `556.0ms`、max `798.6ms`。
  - main/Chainstack：`50/50` 成功，overall p50 `280.2ms`、p90 `331.6ms`、max `544.7ms`。
- 2026-05-11 本地 RPC 收口复核：
  - 新增 `test_execution_rpc.py` 验证 env 优先、主 RPC 共享识别、配置替换、广播 fail-closed。
  - `.venv` 已通过 `test_execution_rpc.py`、`test_launch_execution_pipeline.py`、`test_launch_sell_strategy.py` 和相关脚本 `py_compile`。
- 2026-05-11 新增 RPC 压力观察：
  - `scripts/ops/launch_rpc_pressure_probe.py` 同时测主采集 RPC、backfill RPC、execution RPC 和指定项目的 pool `getReserves` market latency。
  - 本地 `TDS` 小样本已按生产同构入口复测：`.env.local` 提供 `VWR_EXEC_HTTP_RPC_URL`，`execution_rpc.py` 会在进程环境缺失时自动读取该 ignored 文件；输出 `data/backtests/launch-rpc-pressure-probe-local-autoenv-20260511T064241Z.json`，`executionRpcSharedWithMain=false`。
  - 当前本地 `.env.local` 复用生产 execution endpoint，用途是“本地同构测试 -> 通过后同步生产”的单活流程，减少本地与生产环境漂移；本地测试和远端生产不要并行跑同一套交易 RPC。
  - 只有在需要本地长期并行压测或多人同时开发时，才应改为单独 dev/local Chainstack endpoint。
  - `execution_rpc.py` 已加本地广播保护：如果 `VWR_EXEC_HTTP_RPC_URL` 是从本地 `.env.local` 自动加载，真实广播默认阻断；只有显式设置 `VWR_ALLOW_PROJECT_ENV_BROADCAST=1` 才允许本地 canary 广播。
  - 生产灰度前需在远端以 `/etc/virtuals-whale-radar/execution-rpc.env` 运行同一脚本，要求 `executionRpcSharedWithMain=false`。
- 后续如果需要进一步降低延迟，再评估 Chainstack Trader node `lax1` 或多 RPC 同 raw transaction broadcast；Trader node 涉及地区和付费资源选择，必须单独确认后再开。

### Stage 2.5：生产 prewarm simulate 灰度

- 服务：`vwr-launch-prewarm@ROO.service`。
- 输出：`data/execution/launch-prewarm-executor-ROO.jsonl`。
- 模式：`prewarm_simulate`。
- 边界：不读取 burner 私钥、不签名、不广播；只在 BuyIntent 后做订单绑定与 TxSimulator。
- RPC：使用 `/etc/virtuals-whale-radar/execution-rpc.env` 注入的独立 Chainstack execution endpoint；日志必须显示 `rpcSharedWithMain=false`。
- 2026-05-11 远端 smoke：
  - ROO 当前为 `scheduled`，因此只记录 `state_change/not_live`。
  - 日志字段保持 `readOnly=true`、`tradeSent=false`、`broadcastEnabled=false`。
  - 主服务、ROO dry-run、ROO prewarm 均为 `active`。
  - `/health` 与 `/healthz` 正常。
  - active fuse 为空。
  - 执行账本中 `trade_sent=1` 和 `broadcast_enabled=1` 均为 `0`。
- `sign-ready` 灰度仍未启用；该模式会读取 burner 私钥，只能在明确需要签名演练时开启。
- `broadcast` 代码路径已实现，并已为 ROO 安装独立 autobuy systemd 服务；当前 300V 项目上限下已 armed，尚未发生真实买入。
- 生产 systemd 密钥入口优先使用 `EnvironmentFile` 注入的 `VWR_BURNER_PRIVATE_KEY`；执行器只在环境变量不存在时读取 `--secret-file`，避免要求 `vwr` 进程用户直接读取 root-only 密钥文件。

发射前 readiness 检查：

- 脚本：`scripts/ops/launch_readiness_check.py`。
- 作用：只读检查项目字段、active fuse、execution RPC、Base ETH gas、VIRTUAL balance/allowance、订单绑定和 TxSimulator。
- 默认模拟 `25V` 与 `50V` 两档，覆盖当前策略的基础买入和 dip20 加倍买入。
- 输出 `ready=false` 时必须先处理原因，再进入 `sign-ready` 或真实广播阶段。

2026-05-11 ROO readiness 状态：

- 已完成 25V VIRTUAL 授权广播，tx `0x2b5573753c5863f17fc784043956ecafdae04f9adc77a7bd7639226da15d5833`，receipt status `0x1`。
- allowance 已确认到 `25 VIRTUAL`，spender 为 `0x02fe8ec3d9bbf7318eb54590bcc39198a8b47ded`。
- 这是授权交易，不是 ROO 买入；`tradeSent=false`。
- 授权后 25V readiness 中 balance/allowance 通过，但 ROO 仍为 `scheduled`，`buy()` 的 `eth_call / estimateGas` 仍 revert；因此当前只是“钱包准备好 25V 基础买入”，不是“现在可买”。
- 2026-05-11 已追加 300V VIRTUAL 精确授权，tx `0xd7ea8c4ec30601edc67f8579a334abaecab0e38970608c79fbd8e6cc5096b36e`，receipt status `0x1`，allowance 已确认到 `300 VIRTUAL`。
- 授权不要求当前 VIRTUAL 余额足够；后续实际可买额度仍受 `min(balance, allowance, service caps)` 限制。

### Stage 2.6：ROO autobuy armed

- 服务模板：`deploy/systemd/vwr-launch-autobuy@.service`。
- 生产服务：`vwr-launch-autobuy@ROO.service`。
- 输出：`data/execution/launch-autobuy-ROO.jsonl`。
- 生产启动策略：ROO 执行服务不常驻，由 `vwr-launch-roo-start.timer` 在 `2026-05-12 22:25:00 CST` 拉起 `dry-run / prewarm simulate / autobuy broadcast / autosell broadcast`。
- 主采集预热：主程序仍按 `start_at - 30min` 自动进入 `prelaunch`，ROO 为 `2026-05-12 22:30:00 CST`。
- 2026-05-11 远端状态：`vwr-launch-roo-start.timer` 为 `active(waiting)`，下一次触发 `2026-05-12 22:25:00 CST`；执行服务均为 `inactive + disabled`，避免发射前过早占用 RPC 与写日志。
- 模式：`prewarm_broadcast`。
- 广播门禁：service 内置 `VWR_ENABLE_AUTO_BUY_BROADCAST=1`，ExecStart 显式 `--mode broadcast --enable-broadcast`。
- RPC：使用独立 execution Chainstack endpoint，日志显示 `rpcSharedWithMain=false`。
- 上限：`--max-buy-v 50`、`--max-project-v 300`。
- 密钥：`/etc/virtuals-whale-radar/burner-wallet.env`，权限 `root:root 600`，由 systemd `EnvironmentFile` 注入。
- 2026-05-11 启动检查：
  - ROO 仍为 `scheduled`，日志只记录 `state_change/not_live`。
  - `tradeSent=false`，没有广播交易。
  - timer 触发前执行服务不常驻。
  - 主服务 active；dry-run、prewarm simulate、autobuy 改为由 timer 在 22:25 CST 自动启动。
  - `/health` 与 `/healthz` 正常。
  - active fuse 为空。

### Stage 2.7：ROO autosell armed

- 服务模板：`deploy/systemd/vwr-launch-autosell@.service`。
- 生产服务：`vwr-launch-autosell@ROO.service`。
- 输出：`data/execution/launch-autosell-ROO.jsonl`。
- 策略：`dual_roi_large_buy_sell`。
- 触发窗口：税率 `<=30%`。
- 收益率轨道：收益率 `>=30%` 卖原始总仓位 `30%`，收益率 `>=50%` 卖原始总仓位 `50%`。
- 大额买入轨道：单笔买入 `>=5,000 VIRTUAL` 卖原始总仓位 `30%`，单笔买入 `>=8,000 VIRTUAL` 卖原始总仓位 `50%`。
- 两条卖出轨道独立记账；同一刻同时触发时合并为一笔卖出。
- 状态来源：
  - 从 `launch_execution_ledger` 重建本程序买入收到的 token、已卖 token、已卖比例和冷却状态。
  - 每轮读取 burner 当前 token 余额，真实余额低于目标时按余额上限卖出。
  - 从实时 `events` 表读取最新大额买入事件。
- 广播门禁：service 内置 `VWR_ENABLE_AUTO_SELL_BROADCAST=1`，ExecStart 显式 `--mode broadcast --enable-broadcast`。
- 精确授权门禁：service 内置 `VWR_ENABLE_AUTO_SELL_APPROVE=1`，ExecStart 显式 `--auto-approve`；只有目标 token allowance 不足时，才精确授权本次卖出数量。
- RPC：使用独立 execution Chainstack endpoint，默认拒绝共享主采集 RPC 广播。
- 失败处理：sell simulation、approve、sign、broadcast、receipt 任一异常写入 `launch_execution_ledger` 并触发 active fuse。
- 本地 smoke：TDS ended 项目 `autosell_simulate --once` 正常启动并返回 `no_position`，无签名、无广播。

### Stage 3：历史交易 calldata parity

- 已完成。
- SR/ISC 共采集 19 个样本。
- 18 个样本为直接 Virtuals buy route，1 个样本为 alternate/aggregator route。
- 直接 route 的 `to / value / selector / token / amountIn` 与回放库核心字段一致。
- 标准 4 参数交易 exact parity；带 29 bytes 尾部标签交易 canonical prefix parity。

### Stage 4：unsigned tx + eth_call simulation

- 用当前链上状态构造 unsigned tx。
- 只跑 `eth_call / estimateGas / balance / allowance / nonce`。
- 不签名、不广播。

### Stage 5：本地签名但不广播

- burner wallet。
- 本地签名。
- 解码 raw tx 验证字段。
- 不广播。

### Stage 6：小额主网 canary

- 手动确认。
- 单笔极小额度。
- 广播一次。
- 验证 receipt、余额变化和失败恢复。

### Stage 7：自动执行灰度

- 单项目白名单：通过 `--project` 指定，当前 ROO 单项目服务。
- 单笔上限：`--max-buy-v`，ROO 当前为 `50V`。
- 单项目上限：`--max-project-v`，ROO 当前为 `300V`。
- 同一税率档最多一次：执行器会读取 `launch_execution_ledger.trade_sent=1` 记录阻断重复广播。
- 任意 simulation/sign/prewarm/broadcast/receipt 异常熔断。
- 自动卖出边界：生产常驻执行器已接入 ROO timer，但真实 live 窗口里的 SellIntent -> approval/simulation/broadcast/receipt 尚待第一次实盘验证。

## 6. 验收标准

- `StrategyEvaluator` 可在本地 replay 和实时 snapshot 两种来源下产生一致 BuyIntent。
- OrderBuilder 有真实历史交易 parity test。
- TxSimulator 能证明失败时不签名。
- LocalSigner 能证明签名但不广播。
- Broadcaster 默认拒绝广播。
- Canary 前必须有手动确认。
- 所有输出不包含私钥、seed、RPC token。
