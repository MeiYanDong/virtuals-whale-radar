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
  - 授权不要求当前 VIRTUAL 余额足够；实际可买额度仍受 `min(balance, allowance, service caps)` 限制。
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
- [x] `broadcast` 模式下钱包 `balance / allowance` 不足只记录 `readiness_not_ready`，不触发 active fuse。
- [x] `broadcast` 模式下如果未真实发出交易，会回滚本次策略内存状态，避免资金稍后转入后被误判为“该税率档已买过”。
- [x] 修复 `launch_execution_ledger` 后续异常更新把已发送交易 `trade_sent=1 / broadcast_enabled=1` 覆盖回 `0` 的风险，保护同税率档防重和项目上限统计。
- [x] 进入预热前检查 active fuse。
- [x] simulation/sign/prewarm/broadcast/receipt 异常写入执行账本并触发执行熔断。
- [x] `prewarm_simulate` 模式下余额/授权不足记录为 `readiness_not_ready`，不触发 active fuse；`sign-ready` 仍会在 simulation 不绿时触发熔断。
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
  - 上限：`maxBuyV=50`、`maxProjectV=300`。
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
- [ ] 真实 live 项目窗口内验证 BuyIntent -> simulation/prewarm/broadcast/receipt 的完整路径。
- [ ] 真实 live 项目窗口内验证 SellIntent -> approval/simulation/broadcast/receipt 的完整路径。
- [ ] 如果要真正买满 300V，需要把足够 VIRTUAL 转入 burner；授权和服务上限已到 300V 项目预算。

## 6.2 Canary 退出与清仓

- [x] 确认 Virtuals direct sell selector：`sell(uint256,address,uint256,uint256)` / `0xb233e056`。
- [x] 新增通用精确授权脚本：`scripts/ops/approve_erc20_spender.py`。
- [x] 新增卖回 VIRTUAL 脚本：`scripts/ops/sell_virtuals_token.py`。
- [x] 将本轮 canary 买入的 TDS / RRR / AURA / ASDSDA 全部卖回 VIRTUAL。
- [x] 清仓后链上核对：四个 token 余额均为 `0`，对 router/spender 的 token allowance 均为 `0`。
- [x] 卖回合计收到 `3.9223602 VIRTUAL`，最终 burner VIRTUAL 余额 `12.587713615542899411`。

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
- [x] 单项目上限：`--max-project-v`，ROO 当前为 `300V`。
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
