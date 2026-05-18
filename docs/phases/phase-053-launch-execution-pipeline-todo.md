# Phase 053 Launch Execution Pipeline Todo

## 1. 文档冻结

- [x] 创建 Phase 053 子 plan：`docs/phases/phase-053-launch-execution-pipeline-plan.md`。
- [x] 创建 Phase 053 子 todo：`docs/phases/phase-053-launch-execution-pipeline-todo.md`。
- [x] 明确 Phase 052 只负责策略验证，Phase 053 负责执行链路。
- [x] 明确真实交易最终需要接钱包、签名、广播和 receipt 验证。

## 2. StrategyEvaluator

- [x] 新增执行链路脚本骨架：`scripts/ops/launch_execution_pipeline.py`。
- [x] 实现 `DynamicAfter1StrategyEvaluator`。
- [x] 输出 `BuyIntent`。
- [x] 输出 `pause / skip` 原因。
- [x] 保持 `tradeSent=false`。
- [x] 对 SR 样本跑 dry-run：`data/backtests/launch-execution-dry-run-sr-tax95-after1-20260510.json`。
- [x] 对 ISC 样本跑 dry-run：`data/backtests/launch-execution-dry-run-isc-tax89-after1-20260510.json`。
- [x] 新增本地 smoke test：`scripts/ops/test_launch_execution_pipeline.py`。

## 3. OrderBuilder

- [x] 收集 Virtuals 成功买入交易样本：SR/ISC 共 19 个样本。
- [x] 解析 `to / value / method selector / calldata / deadline / slippage`。
- [x] 输出 calldata 研究报告：`docs/phases/phase-053-virtuals-buy-calldata-research-2026-05-10.md`。
- [x] 确认直接买入路由：`0x1a540088125d00dd3990f9da45ca0859af4d3b01`。
- [x] 确认直接买入 selector：`0x706910ff`。
- [x] 确认直接买入函数：`buy(uint256 amountIn_, address tokenAddress_, uint256 amountOutMin_, uint256 deadline_)`。
- [x] 实现标准 4 参数 calldata encoder。
- [x] 实现显式参数的 unsigned buy tx builder：`VirtualsOrderBuilder.build_buy(...)`。
- [x] 做历史交易 calldata parity test：canonical 样本 exact parity，带尾部标签样本 canonical prefix parity。
- [x] 确认 spender/allowance 需求：实际 VIRTUAL spender 为 `0x02fe8ec3d9bbf7318eb54590bcc39198a8b47ded`，不是 direct router。
- [x] 输出 spender trace 报告：`docs/phases/phase-053-virtuals-buy-spender-trace-2026-05-10.md`。
- [x] 接入 allowance 检查，默认查 `allowance(owner, actual_spender)`。
- [x] 完成买入方式通用性审计：`docs/phases/phase-053-virtuals-buy-route-universality-audit-2026-05-10.md`。
- [x] 确认第一版自动买入只支持 `direct_buy`：`to == 0x1a540088125d00dd3990f9da45ca0859af4d3b01` 且 `selector == 0x706910ff`。
- [x] 确认 team/initialization route 和 alternate/aggregator route 不纳入第一版自动买入。
- [x] 将 `BuyIntent` 绑定到具体 token、slippage、deadline。
- [x] 输出 order binding / `amountOutMin` 报告：`docs/phases/phase-053-virtuals-order-binding-minout-2026-05-10.md`。
- [ ] 对 alternate/aggregator route 样本单独归档，不纳入第一版自动买入。

## 4. TxSimulator

- [x] 实现 `eth_call` 模拟。
- [x] 实现 `estimateGas`。
- [x] 检查 VIRTUAL balance。
- [x] 检查 allowance。
- [x] 检查 nonce。
- [x] 检查 deadline。
- [x] 模拟失败时禁止签名。
- [x] 新增只读 probe：`scripts/ops/tx_simulator_probe.py`。
- [x] 真实 RPC probe 输出：`data/backtests/tx-simulator-probe-sr-readonly-20260510.json`。
- [x] 接入 slippage 口径：从报价或当前池状态计算 `amountOutMin`，禁止固定为 0。
- [x] 真实 TDS 只读 probe 验证：能生成非零 `amountOutMin`，余额不足时 `eth_call/estimateGas` 阻断，`tradeSent=false`。
- [x] 并发化 `balance / allowance / nonce / eth_call / estimateGas`，降低冷路径模拟耗时。
- [x] `tx_simulator_probe.py` 优先使用独立 `VWR_EXEC_HTTP_RPC_URL`，输出 `rpcSharedWithMain`，避免发射前预检误走主采集 RPC。
- [x] 新增 `scripts/ops/launch_readiness_check.py`：发射前只读检查项目字段、active fuse、execution RPC、Base ETH gas、VIRTUAL balance/allowance、订单绑定和 TxSimulator。
- [x] 明确 ERC-20 授权不要求当前 VIRTUAL 余额足够；授权交易只要求 burner 有 Base ETH 付 gas，后续可转出的 VIRTUAL 仍受 `min(balance, allowance)` 限制。
- [x] 新增延迟探针：`scripts/ops/launch_latency_probe.py`，只签名不广播，输出 `coldPrepareMs / hotPathLocalMs`。
- [x] Chainstack RRR 延迟探针输出：`data/backtests/launch-latency-probe-chainstack-rrr-20260510.json`，中位 `coldPrepareMs=1278.3ms`，`hotPathLocalMs=12.8ms`。

## 5. LocalSigner

- [x] 设计 burner wallet secret 配置方式：仅允许环境变量 `VWR_BURNER_PRIVATE_KEY`。
- [x] 禁止 CLI 参数传私钥。
- [x] 实现本地签名。
- [x] 验证 raw tx recover sender。
- [x] 签名测试不广播。
- [x] 输出 LocalSigner no-broadcast 报告：`docs/phases/phase-053-local-signer-no-broadcast-2026-05-10.md`。
- [x] 使用真实 burner 钱包做 no-broadcast 演练，签名后不广播，`tradeSent=false`。

## 6. Broadcaster

- [x] 当前 `SafeBroadcaster` 默认拒绝广播。
- [x] `buy_virtual_canary.py` 增加 `sendRawMs / totalToSendAckMs / waitReceiptMs` timing，后续不再用 receipt 时间衡量第一买入提交速度。
- [x] `buy_virtual_canary.py` 支持 `--no-wait-receipt`，用于只测提交 ACK，不等待链上确认。
- [x] 新增 `scripts/ops/prewarmed_buy_canary.py`，把预热阶段和触发广播阶段拆开；默认不广播，只有显式 `--broadcast` 才会发送。
- [x] `prewarmed_buy_canary.py` dry-run 验证：当前 allowance 不足时 `simulationGreen=false`、`broadcasted=false`、`tradeSent=false`。
- [x] 修复 `approve_virtual_spender.py` 授权后即时读取 allowance 可能 stale 的问题：receipt 后轮询确认 allowance。
- [x] `approve_virtual_spender.py` 与 `approve_erc20_spender.py` 优先使用独立 `VWR_EXEC_HTTP_RPC_URL`，输出 `rpcSharedWithMain`。
- [x] `approve_virtual_spender.py` 与 `approve_erc20_spender.py` 支持 `--skip-sign`，可在没有私钥文件时只读验证 approve 的 `eth_call / estimateGas / nonce / fee`，不签名、不广播。
- [x] 2026-05-11 完成 ROO 25V VIRTUAL 授权广播。
  - tx：`0x2b5573753c5863f17fc784043956ecafdae04f9adc77a7bd7639226da15d5833`。
  - receipt status：`0x1`。
  - allowance：`0 -> 25 VIRTUAL`，spender 为 `0x02fe8ec3d9bbf7318eb54590bcc39198a8b47ded`。
  - `tradeSent=false`，本次只是授权，不是 ROO 买入。
  - 授权后 ROO 25V readiness：balance/allowance 已通过；因项目仍为 `scheduled`，`buy()` 的 `eth_call / estimateGas` 仍 revert，尚未达到可买状态。
- [x] 2026-05-11 完成 ROO 300V VIRTUAL 精确授权广播。
  - tx：`0xd7ea8c4ec30601edc67f8579a334abaecab0e38970608c79fbd8e6cc5096b36e`。
  - receipt status：`0x1`。
  - allowance：`25 -> 300 VIRTUAL`，spender 为 `0x02fe8ec3d9bbf7318eb54590bcc39198a8b47ded`。
  - 授权不要求当前 VIRTUAL 余额足够；授权上限不等于项目预算，ROO 实际可买额度仍受 `min(balance, allowance, --max-project-v 150)` 限制。
  - 授权后 readiness：25V 只剩项目未 live 导致的 `ethCall/estimateGas`；50V 不再报 allowance，只剩 balance 与项目未 live。
- [x] 完成冷路径真实 canary：`0.001 VIRTUAL -> RRR`，`sendRawMs=438.6ms`，`totalToSendAckMs=2644.1ms`，receipt `status=1`。
- [x] 完成热路径真实 canary：`0.001 VIRTUAL -> RRR`，预热后 `triggerToSendAckMs=450.6ms`，receipt `status=1`。
- [x] 记录 receipt。
- [x] 验证余额变化和 token 到账。
- [x] 显式 canary allow gate：`buy_virtual_canary.py` 与 `prewarmed_buy_canary.py` 默认不广播，必须传 `--broadcast` 才会发送。

## 6.1 延迟目标

- [x] 明确第一买入考核指标是 `tax_tick -> eth_sendRawTransaction ACK`，不是 `tax_tick -> receipt`。
- [x] 当前冷路径中位可压到约 `1.3s`，但存在 RPC outlier，不能作为生产第一买入主路径。
- [x] 真实 canary 证明预热路径 `trigger -> send ACK` 可低于 `2s`，本轮实测 `450.6ms`。
- [ ] 生产第一买入必须工程化预热路径：提前维护状态、预取 fee/nonce/gas、预构造或预签候选交易，tick 到达时只做本地条件判断和广播。
- [x] 目标：`tax_tick -> send ACK < 2s`；receipt 单独记录，不作为发射第一买入延迟指标。

## 6.1.1 RPC 隔离

- [x] 文档明确采集 RPC 与自动买入 RPC 的并发风险。
- [x] 明确 dry-run emitter 可以共享主流程 RPC，但必须低频、白名单、记录 `rpcSharedWithMain`。
- [x] 明确真实自动买入必须支持独立 `VWR_EXEC_HTTP_RPC_URL`，交易 RPC 不承担 `eth_getLogs` 历史回扫。
- [x] 新增远端轻量 RPC 基准脚本：`scripts/ops/bench_execution_rpc.py`。
- [x] 生产机已配置独立交易 RPC env：`/etc/virtuals-whale-radar/execution-rpc.env`。
  - 当前 `VWR_EXEC_HTTP_RPC_URL` 按用户决策指向 Chainstack Base endpoint。
  - 已创建独立 Chainstack Base Global node：`virtuals-whale-radar-execution` / `ND-554-355-391`。
  - 主流程 Chainstack endpoint hash：`481fbd2573aa`；execution endpoint hash：`493d6968fc13`。
  - ROO dry-run 最新启动日志已显示 `rpcSharedWithMain=false`。
  - 专用 execution Chainstack 复测：`50/50` 成功，overall p50 `283.3ms`、p90 `556.0ms`、max `798.6ms`。
- [x] 新增统一 execution RPC helper：`scripts/ops/execution_rpc.py`。
- [x] `sell_virtuals_token.py`、`buy_virtual_canary.py`、`prewarmed_buy_canary.py`、`launch_latency_probe.py`、`local_signer_probe.py` 已改为优先使用 `VWR_EXEC_HTTP_RPC_URL`，并输出 `rpcSharedWithMain / executionRpcSource`。
- [x] 真实广播路径默认 fail-closed：买入 canary、预热买入 canary、卖出、授权、生产预热执行器在共享主采集 RPC 时会阻断广播，除非显式传 `--allow-shared-rpc-broadcast`。
- [x] 新增 `scripts/ops/test_execution_rpc.py`；本地 `.venv` smoke 已通过 `test_execution_rpc.py`、`test_launch_execution_pipeline.py`、`test_launch_sell_strategy.py` 与相关脚本 `py_compile`。
- [x] 新增只读 RPC 压力观察脚本：`scripts/ops/launch_rpc_pressure_probe.py`，同一报告记录主采集 RPC、backfill RPC、execution RPC、项目 market reserve latency，不签名、不广播、不输出 endpoint token。
- [x] 新增 `scripts/ops/test_launch_rpc_pressure_probe.py`；本地 `.env.local` 已补齐 `VWR_EXEC_HTTP_RPC_URL`，`execution_rpc.py` 会在进程环境缺失时自动读取该 ignored 文件。
- [x] 本地同构 `TDS` pressure probe 通过，输出 `data/backtests/launch-rpc-pressure-probe-local-autoenv-20260511T064241Z.json`，`executionRpcSharedWithMain=false`。
- [x] 加固主程序多进程协作：主库和 event bus SQLite 连接增加 busy timeout；`launch_configs_rev / my_wallets_rev` 改为纳秒级版本，避免同秒变更被 realtime/backfill 漏感知；receipt 读取增加短重试并在 heartbeat 暴露 `receipt_misses`。
- [x] 拆分 writer 事件最高块与 rolling backfill 扫描游标：writer 继续维护 `last_processed_block`，backfill 使用独立 `backfill_last_scanned_block`；rolling backfill 等待本轮 tx 队列处理完成后再推进游标，且 receipt 临时缺失时不推进。
- [x] 修复手动/项目级 scan job：只有 receipt 成功读取并完成处理的 tx 才写入 `scanned_backfill_txs`，避免 RPC 临时返回空 receipt 时被永久标记 scanned。
- [x] `launch_readiness_check.py` 增加 core workflow 检查：runtime pause、event queue、realtime/backfill heartbeat、WSS、active scan jobs、prelaunch/live launch_config；项目不存在时输出 `managed_project_not_found` 而不是 traceback；缺 token/pool 时补齐 `reasons`。
- [x] 本地 `.env.local` 当前复用生产 execution endpoint；口径是“本地同构测试 -> 通过后同步生产”的单活流程，减少配置漂移，本地测试和远端生产不要并行跑同一套交易 RPC。
- [x] 只有在需要本地长期并行压测或多人同时开发时，才改为单独 dev/local Chainstack endpoint。
- [x] `execution_rpc.py` 已加本地广播保护：如果 execution RPC 来自本地 `.env.local`，真实广播默认阻断；只有显式设置 `VWR_ALLOW_PROJECT_ENV_BROADCAST=1` 才允许本地 canary 广播。
- [ ] 若要进一步降低延迟，再评估 Chainstack Trader node `lax1` 或多 RPC 同 raw transaction broadcast。
- [ ] 灰度/真实窗口前在生产机运行 `launch_rpc_pressure_probe.py`，确认 `/etc/virtuals-whale-radar/execution-rpc.env` 下 `executionRpcSharedWithMain=false`，并同时观察采集健康、market latency、execution RPC 延迟。

## 6.1.2 生产预热执行器

- [x] 新增 `scripts/ops/launch_prewarm_executor.py`。
- [x] 复用实时项目取样和 `DynamicAfter1StrategyEvaluator`。
- [x] BuyIntent 后接入订单绑定和 TxSimulator。
- [x] `simulate` 模式不读取私钥、不签名、不广播。
- [x] `sign-ready` 模式只签名并保存 tx hash 摘要，不保存 raw transaction，不广播。
- [x] `broadcast` 模式已接入真实发送路径：simulation green 后签名、`eth_sendRawTransaction`、receipt 验证、账本写入。
- [x] `broadcast` 模式有双门禁：`--enable-broadcast` + `VWR_ENABLE_AUTO_BUY_BROADCAST=1`。
- [x] `broadcast` 模式默认要求独立 `VWR_EXEC_HTTP_RPC_URL`，避免与主采集 RPC 共用。
- [x] `broadcast/sign-ready` 密钥加载优先使用环境变量 `VWR_BURNER_PRIVATE_KEY`，兼容 systemd root-only `EnvironmentFile`。
- [x] `broadcast` 模式接入单笔上限、单项目上限、同一税率档防重复发送。
- [x] `launch_prewarm_executor.py` 启动时从 `launch_execution_ledger.trade_sent=1` 重建已买税率、自有加权成本和上一税率买点，避免 live 窗口内 systemd 重启后丢失 dip20 / 横盘暂停策略状态。
- [x] 新增 `scripts/ops/test_launch_prewarm_executor.py`，覆盖从已发送买入记录恢复策略状态。
- [x] `broadcast` 模式下钱包 `balance / allowance` 不足只记录 `readiness_not_ready`，不触发 active fuse。
- [x] `broadcast` 模式下如果未真实发出交易，会回滚本次策略内存状态，避免资金稍后转入后被误判为“该税率档已买过”。
- [x] 修复 `launch_execution_ledger` 后续异常更新把已发送交易 `trade_sent=1 / broadcast_enabled=1` 覆盖回 `0` 的风险，保护同税率档防重和项目上限统计。
- [x] 进入预热前检查 active fuse。
- [x] `sign-ready/broadcast` 下 simulation/sign/prewarm/broadcast/receipt 异常写入执行账本并触发执行熔断；`simulate` 只读模式只记账不熔断。
- [x] `prewarm_simulate` 模式下余额/授权不足记录为 `readiness_not_ready`，不触发 active fuse；`sign-ready` 仍会在 simulation 不绿时触发熔断。
- [x] `prewarm_simulate` 模式下订单绑定异常、缺 token/pool 也只记账不触发 active fuse，避免只读灰度服务误挡真实 autobuy；`sign-ready/broadcast` 保持异常熔断。
- [x] 本地 TDS ended 烟测通过：无 intent、无签名、无广播。
- [x] 本地广播门禁烟测通过：缺 `--enable-broadcast` 会退出；缺独立 `VWR_EXEC_HTTP_RPC_URL` 会退出；均不会进入交易发送。
- [x] 接入生产 systemd `simulate` 灰度服务。
  - 服务：`vwr-launch-prewarm@ROO.service`。
  - 输出：`data/execution/launch-prewarm-executor-ROO.jsonl`。
  - 当前模式：`prewarm_simulate`，不读取私钥、不签名、不广播。
  - 2026-05-11 远端 smoke：ROO 为 `scheduled`，只记录 `state_change/not_live`，`tradeSent=false`、`broadcastEnabled=false`、`rpcSharedWithMain=false`。
  - 2026-05-11 远端健康检查：主服务、ROO dry-run、ROO prewarm 均 active；`/health` 与 `/healthz` 正常；active fuse 为空；执行账本 `trade_sent=1` 与 `broadcast_enabled=1` 均为 `0`。
- [x] 新增并安装 ROO 生产 `broadcast` armed 服务。
  - 服务模板：`deploy/systemd/vwr-launch-autobuy@.service`。
  - 生产服务：`vwr-launch-autobuy@ROO.service`。
  - 启动策略：由 `vwr-launch-roo-start.timer` 在 `2026-05-12 22:25:00 CST` 拉起；主采集仍在 `2026-05-12 22:30:00 CST` 自动进入 `prelaunch`。
  - 2026-05-11 远端状态：timer `active(waiting)`；执行服务均为 `inactive + disabled`，避免发射前过早占用 RPC；timer 到点后自动启动。
  - 模式：`prewarm_broadcast`，日志显示 `broadcastEnabled=true`、`rpcSharedWithMain=false`。
  - 上限：`maxBuyV=50`、`maxProjectV=150`；300V 是授权上限，不是本项目预算。
  - ROO 仍为 `scheduled`，当前只记录 `state_change/not_live`，`tradeSent=false`。
- [x] 新增生产自动卖出常驻执行器：`scripts/ops/launch_sell_executor.py`。
  - 读取同一份项目、事件、市场和执行账本数据。
  - 按 `dual_roi_large_buy_sell` 规则判断卖出。
  - `simulate` 模式不读取私钥、不签名、不广播。
  - `broadcast` 模式要求 `--enable-broadcast` + `VWR_ENABLE_AUTO_SELL_BROADCAST=1` + 独立 `VWR_EXEC_HTTP_RPC_URL`。
  - token allowance 不足时，仅在 `--auto-approve` + `VWR_ENABLE_AUTO_SELL_APPROVE=1` 同时存在时做“精确授权当前卖出数量”。
  - simulation/sign/approve/broadcast/receipt 异常写入 `launch_execution_ledger` 并触发 active fuse。
- [x] 新增 ROO 生产 autosell armed 服务模板：`deploy/systemd/vwr-launch-autosell@.service`。
  - 服务：`vwr-launch-autosell@ROO.service`。
  - 输出：`data/execution/launch-autosell-ROO.jsonl`。
  - 启动策略：由 `vwr-launch-roo-start.timer` 与 dry-run / prewarm / autobuy 一起拉起。
- [x] 本地 autosell smoke：TDS ended 项目只读启动成功，结果 `no_position`，无签名、无广播。
- [x] 新增 autosell 状态重建测试：`scripts/ops/test_launch_sell_executor.py`。
- [x] 修复 autosell 大额买入去重：不再把“已看见但尚未触发/尚未成功卖出”的买入 tx 写入内存去重；只根据成功卖出账本里的 `processedLargeBuyTxs` 去重，并用 `--catch-up-events-sec` 滚动窗口读取近期事件，避免税率尚未进入 `<=30%` 时提前跳过大单。
- [x] ROO 复盘修正执行账本 `mode`：同一 intent 先由 simulate 写入、后由 broadcast 成功执行时，`mode` 随签名/广播/receipt 更新，避免审计时出现 `prewarm_simulate + trade_sent=1` 的假象。
- [x] 补齐 `deploy_production_safe.sh` 白名单：`docs/源码导读图.md` 与 `scripts/ops/test_launch_prewarm_executor.py` 会随生产同步带上。
- [x] 新增 live 发射档案归档脚本：`scripts/ops/archive_launch_project.py`，只读生产 SQLite，输出 `manifest/project/samples/events/execution-ledger/fuses/summary/archive.db`。
- [x] 修复归档脚本配置边界：归档只读取 `SQLITE_PATH` 或显式 `--sqlite-path`，不再解析 RPC 环境变量占位，保证 SSH 手工归档可运行。
- [x] `live_strategy_dry_run.py` 新增 `--full-samples-jsonl`，支持每轮采样写入独立 `launch-samples-<PROJECT>.jsonl`。
- [x] 新增生产只读 recorder 模板：`deploy/systemd/vwr-launch-dryrun@.service`，默认同时写 `live-strategy-dry-run-%i.jsonl` 与 `launch-samples-%i.jsonl`。
- [x] `recalc_dynamic_buy_strategy.py` 与 `recalc_dual_sell_strategy.py` 支持 `--report <archive>/summary.json`，不再只能走 SR/ISC 默认入口。
- [x] 本地归档 smoke：TDS 本地 DB 导出成功；指定本地 sample JSONL 后，dynamic/dual sell 回测脚本可读取 archive summary。
- [x] 2026-05-15 生产状态复核：当前生产部署已包含 Phase 053/054 代码与文档同步；具体部署 commit 以服务器 `DEPLOYED_COMMIT` 为准。`writer / realtime / backfill / SignalHub / nginx` 均 active，`/health ok=true`，`queueSize=0`，`pendingTx=0`，`runtimePaused=false`，`/healthz status=ok`。
- [x] 真实 live 项目窗口内验证 BuyIntent -> simulation/prewarm/broadcast/receipt 的完整路径：
  - 2026-05-15 复核 ROO 生产账本与链上 receipt，`launch_execution_ledger` 有 2 笔 `would_buy / receipt_success / trade_sent=1 / broadcast_enabled=1`。
  - 买入 tx：`0xa1a2786e18e1b83f66724d4b930bd42ad73883df3f5f86c3bc21bd8ef0afd950`，链上 receipt `status=0x1`，block `45905833`。
  - 买入 tx：`0xcf25aede650a00f134355ba73e8407fced8ccbd7c634c093919a09f95c4806d5`，链上 receipt `status=0x1`，block `45907033`。
- [x] 真实 live 项目窗口内验证 SellIntent -> approval/simulation/broadcast/receipt 的完整路径：
  - 2026-05-15 复核 ROO 生产账本与链上 receipt，`launch_execution_ledger` 有 2 笔 `sell / receipt_success / trade_sent=1 / broadcast_enabled=1`。
  - 卖出 tx：`0x87ccc9c6935362af1786eeab5974c52cafc938c404a0b275de7be2b117a7398b`，链上 receipt `status=0x1`，block `45906445`。
  - 卖出 tx：`0xf476b21b47df21a012f47c62a2c90057a1d03795dedb50272b0107e9b291e7ff`，链上 receipt `status=0x1`，block `45907039`。
  - 卖出链路包含精确 token approve；相关 approval receipt 在 `launch-autosell-ROO.jsonl` 中记录为 `approval_confirmed`。
- [x] 2026-05-15 当前即时 canary 边界已确认：ROO 已 ended，新的 `0.001V` launch direct-buy readiness 会在 `eth_call/estimateGas` 失败；这不是 RPC 或钱包故障，下一次只能在真实 live 项目窗口复测新的 canary。
- [ ] 如果要真正买满 ROO 150V 项目预算，需要把足够 VIRTUAL 转入 burner；授权已到 300V，服务上限已收紧为 150V。
- [x] 2026-05-16 完成 ROO live regression 标准归档：`sampleCount=7993`、`eventCount=505`、`ledgerCount=240`、`warnings=[]`，报告见 `docs/phases/phase-053-roo-live-regression-2026-05-16.md`。
- [x] 2026-05-16 完成 ROO canonical 买入回放：当前主策略买入 `6` 次，总投入 `150V`，最终收益率 `+31.8845%`。
- [x] 2026-05-16 完成 ROO canonical 卖出回放：卖出 `1` 次，最终收益率 `+32.7369%`，相对纯持有提升 `+0.846%`。
- [x] 2026-05-16 重新查链确认 ROO 2 笔买入与 2 笔卖出 receipt 均为 `status=0x1`。
- [x] 新增通用 live 项目启动编排脚本：`scripts/ops/schedule_launch_services.py`，替代后续继续复制 `vwr-launch-roo-start.timer` 的手工流程。
- [x] 新增本地 prewarm systemd 模板：`deploy/systemd/vwr-launch-prewarm@.service`。
- [x] 新增通用启动编排测试：`scripts/ops/test_schedule_launch_services.py`。
- [x] `deploy_production_safe.sh` 白名单加入通用启动脚本、prewarm 模板、测试脚本和 ROO 回归报告。

## 6.1.1 ROO 开盘即时验证

- [ ] 22:25 CST 确认 `vwr-launch-roo-start.timer` 已拉起 `dry-run / prewarm / autobuy / autosell`。
- [ ] 23:00 CST 后立刻确认主链路健康：`/health`、`/healthz`、active fuse、realtime/backfill heartbeat、ROO `status=live`、market 数据时间戳和 block 持续更新。
- [ ] 开盘后做 `0.1 VIRTUAL` 真实 buy canary；receipt 成功后只卖出本次买入 receipt 中的 `receiptTargetReceivedRaw`，禁止用 `amount-raw=max`，避免误卖自动策略仓位。
- [ ] 检查自动买入执行器：`launch-autobuy-ROO.jsonl` 与 `launch_execution_ledger` 有明确 `decision_reason / trade_sent / receipt_success` 或清晰的未触发原因，项目累计买入不超过 `150V`。
- [ ] 检查自动卖出执行器：`launch-autosell-ROO.jsonl` 不出现 approval/simulation/broadcast/receipt 异常；如果无持仓或未满足税率/收益/大单条件，应清晰记录未触发原因。
- [ ] 检查团队/初始化购买过滤：ROO overview 的 whaleBoard 中，首分钟零税且当时预期应有税的地址应 `costExcluded=true`，不计入打新成本位；大户榜单 UI 不展示团队地址。

## 6.2 Canary 退出与清仓

- [x] 确认 Virtuals direct sell selector：`sell(uint256,address,uint256,uint256)` / `0xb233e056`。
- [x] 新增通用精确授权脚本：`scripts/ops/approve_erc20_spender.py`。
- [x] 新增卖回 VIRTUAL 脚本：`scripts/ops/sell_virtuals_token.py`。
- [x] 将本轮 canary 买入的 TDS / RRR / AURA / ASDSDA 全部卖回 VIRTUAL。
- [x] 清仓后链上核对：四个 token 余额均为 `0`，对 router/spender 的 token allowance 均为 `0`。
- [x] 卖回合计收到 `3.9223602 VIRTUAL`，最终 burner VIRTUAL 余额 `12.587713615542899411`。
- [x] 2026-05-18 生产 TDS internal-market canary：`0.1 VIRTUAL` 买入、exact TDS 授权、exact amount 卖回均成功，receipt 均为 `0x1`。
- [x] 修复 `sell_virtuals_token.py` 的 `PoolQuote` 字段缺失崩溃，并补充 sell binder 无网络测试。
- [x] TDS canary 收尾确认：TDS 余额 `0`、TDS sell allowance `0`、active fuse `0`、服务健康。
- [x] 新增 `scripts/ops/full_window_auto_trigger_canary.py`，验证 live 窗口样本流自动触发生产买入/卖出执行器。
- [x] 2026-05-18 12:42 CST 完成 TDS 全窗口自动触发链路 canary：fixture tax `95%` 自动买入 `0.01 VIRTUAL`，tx `0x95dd79671943b3a700beba94073fd0089eef404c5ab42d3a8fac685dcc345bb4`，receipt `0x1`；fixture tax `92%` 强制自动卖出，tx `0x45f81a89de82f9e283856127fcbe329d2fea5ec302a4e561b9f5632015767130`，receipt `0x1`；最终 `tdsBalanceRawAfter=0`。该测试只证明自动触发链路，不代表真实项目税率走势或生产卖出税率策略。
- [x] 全窗口自动触发 canary 已修复 receipt 后余额读取 stale：买入后等待 token balance 可见，卖出后等待 token balance 归零。
- [x] 全窗口自动触发 canary 已修复账本污染：卖出评估只读取本次 run 的 buy/sell strategy 记录。
- [x] `full_window_auto_trigger_canary.py` 默认卖出税率上限改回 `30%`；高税率强制卖出 canary 必须显式传 `--force-high-tax-sell-canary`。
- [x] 新增 `scripts/ops/historical_live_auto_trigger_canary.py`，用真实历史样本流验证自动触发、运行时改参热加载和真实广播，而不是人工 fixture。
- [x] 2026-05-18 14:33 CST 完成 SR 历史样本驱动 TDS internal-market 真实 canary：sample `30` 买入改参后热加载，sample `55` / tax `95%` 自动买入 `0.01 VIRTUAL`，tx `0x541481388328fb7a8181b05ed749518c0fffc605b05badada5b5a8db584062e5`，receipt `0x1`；sample `700` 卖出改参后热加载，sample `819` / tax `30%` 自动卖出，tx `0xce9d5637f82894ef2bfd2dc403664b6f143ba58b943ac3d0c7fc322fb8c47b0a`，receipt `0x1`；summary `ok=true`。
- [x] 历史 canary 收尾：TDS 余额 `0`、TDS sell allowance `0`、active fuse `0`、VIRTUAL allowance 精确 `10 VIRTUAL`，并恢复 TDS 买入/卖出运行时配置为 disabled simulate。
- [x] `historical_live_auto_trigger_canary.py` 增加 `--sell-trigger-mode price_zero`，用于 canary 路径在 `tax <= 30%` 后验证自动卖出执行链路，不要求正收益；生产卖出策略仍由自动卖出配置决定。
- [x] 2026-05-18 15:35-15:36 CST 远端生产库候选筛选完成：当前只有 `TDS / VOID` direct-buy readiness 通过；其他生产项目和 SignalHub 未来项目当前不可买或 simulation 失败。
- [x] 远端漂移已修复：同步当前 canary / buy / sell 执行脚本和 `virtuals_bot.py`，并补齐 `launch_sell_runtime_configs.custom_rules_json`；测试过程中生产服务保持 active，健康检查正常。
- [x] 远端 TDS 历史样本 canary 通过：sample `55` 买入 tx `0x0b25e9fbc0fd7dbdba92aa3411f15c25efbbcb0d1a5eae898d61959f642571c1`，sample `819` 卖出 tx `0xcec3e409a2ab999fb4fd6443dc5adb194793b1b717ea34eb352f2de4bb966b19`，最终余额 `0`、active fuse `0`。
- [x] 远端 VOID 历史样本 canary 通过：sample `55` 买入 tx `0x11cb1c901df209424366389ec01cf6131f38daef0a76583be7c76d0f679ca90f`，sample `819` 卖出 tx `0xe02cd7b85b9a6973f9f40a0182d5d960985d31476d84deda9b7cec3e680fd718`，最终余额 `0`、active fuse `0`。
- [x] 本地临时补测 `RRR / AURA / ASDSDA` 三个内盘标的，均完成 SR `1089` 样本驱动自动买入、运行中卖出配置热加载、`tax 30%` 后自动卖出，summary 均 `ok=true`；临时项目行和运行时配置已清理。
- [x] `approve_virtual_spender.py` 和 `approve_erc20_spender.py` 新增 `--force-exact`，支持强制降额授权和撤销到 `0`，exact 模式等待 allowance 等于目标值。

## 7. ExecutionLedger

- [x] 设计执行记录表：`launch_execution_ledger`。
- [x] 新增 Storage 写入/查询 API：`upsert_launch_execution_record`、`get_launch_execution_record`、`list_launch_execution_records`。
- [x] `live_strategy_dry_run.py` 已把 `would_buy` / `pause` 写入执行账本，仍保持 `tradeSent=false`、`broadcastEnabled=false`。
- [x] `prewarmed_buy_canary.py` 支持可选账本写入 simulation、sign、broadcast、receipt 状态。
- [x] 账本阶段写入不保存 raw transaction，只保存 signed/broadcast tx hash 和 receipt 摘要。
- [x] 支持按项目查询最近执行记录。
- [x] 新增执行熔断表 `launch_execution_fuses`。
- [x] 新增执行熔断 API：trigger / get active / clear / list。
- [x] 新增执行熔断运维脚本：`scripts/ops/launch_execution_fuse.py`。
- [x] `prewarmed_buy_canary.py` 在 active fuse 存在时阻断 `--broadcast`。
- [x] `prewarmed_buy_canary.py` 在 simulation/sign/broadcast/receipt/canary 异常时触发执行熔断。
- [x] 本地验证 list / clear active fuse。
- [x] 将 active fuse 检查接入生产预热执行器安全骨架。
- [ ] 支持按策略版本回放。

## 8. 灰度上线

- [x] 单项目白名单：通过 `--project` 指定单项目执行器。
- [x] 单笔上限：`--max-buy-v`，ROO 当前为 `50V`。
- [x] 单项目上限：`--max-project-v`，ROO 当前为 `150V`。
- [x] 同一税率档最多一次：读取执行账本中 `trade_sent=1` 的同税率记录阻断重复广播。
- [x] canary 路径任意 simulation/sign/broadcast/receipt 异常自动熔断。
- [x] 生产预热执行器 simulation/sign/prewarm/broadcast/receipt 异常自动熔断。
- [x] 新增 realtime dry-run emitter 脚本：`scripts/ops/live_strategy_dry_run.py`，只记录 would-buy，不构造、不签名、不广播。
- [x] ROO 先上线 realtime dry-run emitter，只记录 would-buy，不广播。
  - 生产服务：`vwr-launch-dryrun@ROO.service`。
  - 输出：`data/execution/live-strategy-dry-run-ROO.jsonl`。
  - 当前按用户决策使用独立 Chainstack execution endpoint，仍只记录 would-buy，不广播。
- [x] ROO 先上线 prewarm simulate 灰度服务，只做 BuyIntent 后的订单绑定与模拟，不签名、不广播。
  - 生产服务：`vwr-launch-prewarm@ROO.service`。
  - 输出：`data/execution/launch-prewarm-executor-ROO.jsonl`。
  - 当前按用户决策使用独立 Chainstack execution endpoint，日志显示 `rpcSharedWithMain=false`。
- [x] ROO 已上线 autobuy armed 服务：`vwr-launch-autobuy@ROO.service`，由 timer 拉起，因项目未 live 尚未发送交易。
- [x] ROO 已接入 autosell armed 服务：`vwr-launch-autosell@ROO.service`，由 timer 拉起，只有持仓且满足卖出条件才会发送交易。
