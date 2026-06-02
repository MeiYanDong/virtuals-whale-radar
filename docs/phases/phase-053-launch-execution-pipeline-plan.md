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
- ROO 当前上限：`--max-buy-v 50`、`--max-project-v 150`，匹配当前策略的 25V 基础买入、50V dip20 加倍买入和 150V 项目预算。
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

### 4.8.1 正常税率项目跟单策略

2026-05-31 新增默认跟单策略，用于正常税率 live 窗口：

- 跟单地址：`0xe0b51bbf7af8bff0a8cd422e4b5f17aa0824969d`。
- 触发范围：仅目标项目 `live` 窗口内，该地址在同一项目的买入事件。
- 买入金额：`floor(对方消耗 VIRTUAL / 4)`；结果小于 `1V` 时只记 skipped，不广播。
- 管理员控制：`launch_strategy_runtime_configs` 保存 `follow_enabled / follow_wallet / follow_ratio_pct`；前端以独立“跟单买入”板块展示，和“含税估算 FDV 限价单”平级，不放入大户榜单策略卡；当前地址只展示，只保留启用、停用和保存比例动作，默认 `25%`。
- 优先级：普通大户榜单策略 > 跟单策略 > 含税估算 FDV 限价单。
- 预算口径：`vwr-launch-autobuy@.service` 使用 `--project-cap-scope project`，普通大户策略、跟单策略、FDV 限价单共享同一个 `max_project_v`；跟单策略不叠加大户榜单、税率、FDV、横盘跳过或抄底条件。
- 防重复：同一 source tx hash 在跟单账本中只允许触发一次；跳过记录也会阻断重复处理。
- 关闭方式：执行器支持 `--disable-follow-trade`，默认不关闭。

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

### 4.10 无狙击税开盘秒买执行器

2026-05-24 针对 ORION 这类 `BONDING_V5 + antiSniperTaxType=0` 项目，新增独立开盘秒买链路：

- 执行器：`scripts/ops/launch_open_sniper_executor.py`。
- 适用边界：只用于官方上下文确认无反狙击税的项目；broadcast 模式禁止跳过官方 no-tax 检查。
- 触发方式：不等待固定开盘时刻单次发送，而是在开盘前进入探测窗口，持续对预构造交易做 `eth_call`；任一 probe 返回可买，立刻广播。
- 阶段划分：
  - T-600s：prepare，维护项目、税率、余额、授权、nonce/fee/gas、订单绑定和预签候选。
  - T-300s：high probe，生产配置 `0.05s` poll，`2` workers。
  - T-90s：ultra probe，生产配置 `0.02s` poll，`2` workers。
- RPC 方式：
  - `VWR_PROBE_HTTP_RPC_URLS` 用于并发探测。
  - `VWR_BROADCAST_HTTP_RPC_URLS` 用于同一 signed raw tx fanout 广播。
  - raw transaction 只签一次，同一 nonce 同一笔交易发到多个 provider，不并列签多笔交易。
  - 日志只输出脱敏 label，不输出 endpoint token。
- 预算边界：ORION 当前 systemd 模板为首笔 `100 VIRTUAL`，项目上限 `100 VIRTUAL`；首笔成功后，后续只保留独立含税 FDV 限价单。
- 2026-05-26 复盘修正：
  - ORION 官方 start time 后，链上首批成交实际出现在 `00:01:09 CST`，说明无税项目仍可能存在“官方时间已到但 direct buy 继续 revert”的延迟窗口。
  - 旧版本在 high/ultra probe 阶段没有按 `presign_refresh_sec` 持续重签；如果开盘后价格被第一批买入推高，旧 `amountOutMin` 会卡住 `eth_call`，导致直到候选过期才重新签名。
  - 执行器已改为 high/ultra 阶段也持续按 `presign_refresh_sec` 重签，生产模板降为 `0.5s`；并在开盘后遇到指定报价失效 selector 时立即重签并同轮复探。
  - 2026-05-26 二次修正：无税开盘秒买不再绑定开盘前池子报价，不再读取 reserve 计算保护价；`open-sniper` 直接构造 `buy(amountIn, token, amountOutMin=1, deadline)`，用极低 `amountOutMin` 表达市价抢买。`eth_call` 只负责判断当前是否可买，避免旧报价在开盘瞬间失效。
  - 生产实例若存在项目级 systemd drop-in，会覆盖模板 `ExecStart`；本次已同步修复 ORION drop-in，保留 `300V` 与 `5/6 gwei`，同时补齐 `--presign-refresh-sec 0.5` 和 `--requote-revert-selectors 0x850c6f76`。后续任意单项目覆盖必须同时核对热路径参数。
  - 增加 `--post-trigger-direct-fire` 作为显式准点直发开关，但默认不启用；ORION 证明盲发可能在合约未开放窗口烧掉 nonce，应优先使用“热重签 + 探测成功即 fanout”的安全极速路径。
  - 最优版热路径新增广播后短确认：首轮 raw tx fanout 后快速查 receipt/nonce；若同 nonce 未确认且交易未过 deadline，则同 nonce 提高 fee 后二次 fanout，减少 mempool 卡单风险。
  - 无税项目的 follow-up 限价单可启用 `--require-open-sniper-before-fdv-limit`：首笔 open-sniper 未发出前，FDV 限价单只记录阻断状态，不抢开盘 nonce。
  - `schedule_launch_services.py` 同时选择 `open-sniper,fdv-limit` 时会自动生成 `vwr-launch-fdv-limit@<PROJECT>.service.d/10-require-open-sniper.conf`，避免下次靠人工记忆配置 gate。
  - 通用化入口：`schedule_launch_services.py --auto-profile` 会读取目标项目的 Virtuals 官方 `launchInfo`，复用 `resolve_buy_tax_schedule` 分类 profile。`no_tax_open_sniper` 自动调度 `open-sniper,fdv-limit,autosell`；`taxed_60s/taxed_98m/taxed_default` 自动调度正常 `dryrun,prewarm,autobuy,autosell`；`unknown_blocked` 直接失败，不生成真实调度。
  - `--auto-profile` 若未传 `--start-at`，使用生产库 `managed_projects.start_at`；输出 JSON 会包含 `launchProfile` 证据，便于发射前人工核对官方字段。

压测结论：

- 本地 Base RPC smoke：Chainstack execution p50 约 `120ms`、p90 约 `139ms`；Ankr p50 约 `251ms`、p90 约 `291ms`。
- 本地可买成功 race：`2` workers p50 约 `115ms`、p90 约 `149ms`；`64` workers p50 约 `287ms`，说明盲目加 worker 会变慢。
- 远端 execution RPC smoke：Chainstack p50 约 `68ms`、p90 约 `72ms`；Ankr p50 约 `206ms`、p90 约 `228ms`。
- 远端 ORION closed-probe 压测：`2` workers 约 `7.7 eth_call/s`、平均 `241ms`；`64` workers 可承受约 `160 eth_call/s`，但平均延迟约 `375ms`。
- 生产选择：稳定不报错前提下，T-300/T-90 均使用 `2` workers；这是当前实测的最低延迟组合。

2026-05-24 生产落地：

- ORION 已加入生产 `managed_projects`，`signalhub_project_id=76475`，start time 为 `2026-05-26 00:00:54 CST`。
- 官方 no-tax 校验通过：`factory=BONDING_V5`、`antiSniperTaxType=0`、`buyTaxRate=1`。
- 已安装 systemd 模板：
  - `deploy/systemd/vwr-launch-open-sniper@.service`
  - `deploy/systemd/vwr-launch-fdv-limit@.service`
- 已创建 timer：
  - `vwr-launch-orion-start.timer`：`2026-05-25 23:30:54 CST` 拉起 `open-sniper` 和 `fdv-limit`。
  - `vwr-launch-orion-archive.timer`：`2026-05-26 01:49:54 CST` 归档。
- 核验状态：timer enabled；`vwr-launch-open-sniper@ORION.service` 和 `vwr-launch-fdv-limit@ORION.service` 当前 inactive，等待 timer；生产 `/health` 与 `/healthz` 正常。
- 2026-05-24 15:49 CST preflight：
  - core workflow ready，event queue `0`，pending tx `0`，active fuse `0`。
  - execution RPC 与主采集分离，probe/broadcast RPC 池已配置。
  - VIRTUAL allowance 已够 `300V`，Base ETH gas 充足。
  - burner 当前 VIRTUAL 余额约 `1.67V`，不足首笔 `100V`；发射前必须转入足额 VIRTUAL，否则 open-sniper 会在 readiness 阶段阻断，不触发 active fuse。
  - ORION 当前无含税 FDV 限价单；`fdv-limit` 服务会启动但没有订单可执行。
- ORION 无狙击税自动卖出约定：
  - 自动卖出默认关闭，由管理员在前端手动开启。
  - `autosell` 服务随 ORION timer 一起启动，运行时配置 disabled 时只记录阻断，不真实卖出；这样管理员手动开启后执行器可以下一轮热加载生效。
  - 不再单独设置“无税卖出窗口”；当前 `1%` 税率天然满足现有 `max_tax_rate=30` 安全门，真正卖出仍必须同时满足收益率与大单条件。
  - ORION 配置使用 `dual_roi_large_buy_sell`，显式保持 `customRules=[]`，避免自定义多规则累加语义；卖出档位保持目标仓位 `30% / 50%`。
  - 冷却时间 `10s`，大单回看窗口 `30s`。
  - 2026-05-24 21:31 CST 已执行生产变更：`vwr-launch-orion-start.service` 现在同时启动 `vwr-launch-open-sniper@ORION.service`、`vwr-launch-fdv-limit@ORION.service` 和 `vwr-launch-autosell@ORION.service`。
  - 2026-05-24 21:31 CST 已写入 ORION disabled 自动卖出配置：`enabled=0`、`mode=simulate`、`customRules=[]`、冷却 `10s`、大单回看 `30s`。
  - 只读验证通过：autosell simulate once 读取到 disabled 配置并输出 `runtime_config_disabled`，不签名、不广播、不卖出。

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
- 2026-05-18 追加真实生产 canary：选择已结束但仍有 internal market 的 `TDS`，验证 `0.1 VIRTUAL` 买入 -> exact TDS 授权 -> exact amount 卖回，三笔交易 receipt 均为 `0x1`，执行 RPC 与主采集 RPC 保持分离。
- 本次验证修复了 `sell_virtuals_token.py` 的 sell quote 结构兼容问题；`PoolQuote` 新增字段后，卖出脚本必须显式填充 `effective_slippage_bps / buy_tax_rate_pct / tax_adjusted_amount_out_raw`。
- 收尾链上核对：TDS 余额 `0`、TDS sell allowance `0`、active fuse `0`，主程序 `/health` 与 SignalHub `/healthz` 正常。

全窗口自动触发 canary：

- 新增 `scripts/ops/full_window_auto_trigger_canary.py`，用于验证 live 窗口样本流自动触发执行器，而不是手动调用买卖脚本。
- 验证路径：99 tick 人工 fixture 样本流 -> 生产 `DynamicAfter1StrategyEvaluator` -> `launch_prewarm_executor.prewarm_intent(...)` -> receipt -> 后续样本 -> 生产卖出 evaluator -> `launch_sell_executor.execute_sell_decision(...)` -> exact approve/sell receipt。
- 2026-05-18 12:42 CST，TDS `0.01 VIRTUAL` 链路实测通过：fixture tax `95%` 自动买入 tx `0x95dd79671943b3a700beba94073fd0089eef404c5ab42d3a8fac685dcc345bb4`，receipt `0x1`；fixture tax `92%` 强制自动卖出 tx `0x45f81a89de82f9e283856127fcbe329d2fea5ec302a4e561b9f5632015767130`，receipt `0x1`。
- 报告：`data/execution/full-window-auto-trigger-canary-TDS-20260518-124213-summary.json`，`ok=true`、`paperOnly=false`、`post_buy_balance_visible=1`、`post_sell_balance_zero=1`、`tdsBalanceRawAfter=0`。
- 脚本已处理 receipt 后余额读取 stale：买入后等待 token balance 可见，卖出后等待 token balance 归零。
- 脚本已隔离本次 run 的执行账本：卖出评估只读取本次自动触发 canary 的 buy/sell strategy 记录，避免被 TDS 历史 canary 记录污染 position 口径。
- 这次高税率卖出使用的是强制链路 canary，不代表真实项目税率走势或生产卖出策略；脚本默认卖出税率上限已改回 `30%`，高税率强制卖出必须显式传 `--force-high-tax-sell-canary`。

历史样本驱动真实 canary：

- 新增 `scripts/ops/historical_live_auto_trigger_canary.py`，用于把真实历史发射样本作为触发源，同时在当前可交易 internal market 上真实广播小额买卖。
- 验证路径：SR `1089` 个历史样本 -> sample `30` 写入买入改参 -> `strategy_config_reloaded` -> sample `55` / tax `95%` 自动买入 TDS -> sample `700` 写入卖出改参 -> `sell_config_reloaded` -> sample `819` / tax `30%` 自动卖出 TDS。
- 2026-05-18 14:33 CST，TDS 小额链路实测通过：买入 tx `0x541481388328fb7a8181b05ed749518c0fffc605b05badada5b5a8db584062e5`，卖出 tx `0xce9d5637f82894ef2bfd2dc403664b6f143ba58b943ac3d0c7fc322fb8c47b0a`，两笔 receipt 均 `0x1`。
- 报告：`data/execution/historical-live-auto-trigger-canary-TDS-SR-20260518-143334-summary.json`，`ok=true`、`strategy_config_reloaded=1`、`sell_config_reloaded=1`、`post_sell_balance_zero=1`、active fuse `0`。
- 收尾状态：TDS 余额 `0`、TDS sell allowance `0`、VIRTUAL buy allowance 精确恢复 `10 VIRTUAL`，TDS 运行时买入/卖出配置恢复 disabled simulate。
- `approve_virtual_spender.py` 与 `approve_erc20_spender.py` 新增 `--force-exact`，用于强制降额授权和撤销到 `0`；exact 模式必须确认链上 allowance 等于目标值。

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
- `broadcast` 代码路径已实现，并已为 ROO 安装独立 autobuy systemd 服务；当前 150V 项目上限下已 armed，尚未发生真实买入。
- 生产 systemd 密钥入口优先使用 `EnvironmentFile` 注入的 `VWR_BURNER_PRIVATE_KEY`；执行器只在环境变量不存在时读取 `--secret-file`，避免要求 `vwr` 进程用户直接读取 root-only 密钥文件。

发射前 readiness 检查：

- 脚本：`scripts/ops/launch_readiness_check.py`。
- 作用：只读检查项目字段、active fuse、execution RPC、Base ETH gas、VIRTUAL balance/allowance、订单绑定和 TxSimulator；同时检查主采集协作状态，包括 runtime pause、event queue、realtime/backfill heartbeat、WSS 状态、active scan jobs，以及 prelaunch/live 阶段是否已经生成 launch_config。
- 默认模拟 `25V` 与 `50V` 两档，覆盖当前策略的基础买入和 dip20 加倍买入。
- 输出 `ready=false` 时必须先处理原因，再进入 `sign-ready` 或真实广播阶段。
- 如果本地或远端项目不存在，脚本输出结构化 `managed_project_not_found`，不再 traceback；live 前应优先确认 `coreWorkflowReady=true`，否则自动买卖即使钱包/RPC 准备好，也可能因为采集协作未就绪而延迟。

2026-05-11 ROO readiness 状态：

- 已完成 25V VIRTUAL 授权广播，tx `0x2b5573753c5863f17fc784043956ecafdae04f9adc77a7bd7639226da15d5833`，receipt status `0x1`。
- allowance 已确认到 `25 VIRTUAL`，spender 为 `0x02fe8ec3d9bbf7318eb54590bcc39198a8b47ded`。
- 这是授权交易，不是 ROO 买入；`tradeSent=false`。
- 授权后 25V readiness 中 balance/allowance 通过，但 ROO 仍为 `scheduled`，`buy()` 的 `eth_call / estimateGas` 仍 revert；因此当前只是“钱包准备好 25V 基础买入”，不是“现在可买”。
- 2026-05-11 已追加 300V VIRTUAL 精确授权，tx `0xd7ea8c4ec30601edc67f8579a334abaecab0e38970608c79fbd8e6cc5096b36e`，receipt status `0x1`，allowance 已确认到 `300 VIRTUAL`；这是授权上限，不等于本项目买入预算。
- 授权不要求当前 VIRTUAL 余额足够；ROO 后续实际可买额度仍受 `min(balance, allowance, --max-project-v 150)` 限制。

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
- 上限：`--max-buy-v 50`、`--max-project-v 150`。
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
- 2026-05-13 修正后触发：大额买入必须由自身收益率确认，有效卖出目标取收益率门槛和大额买入门槛的较低值。
- 典型触发：收益率 `>=30%` 且单笔买入 `>=5,000 VIRTUAL` 卖原始总仓位 `30%`；收益率 `>=50%` 且单笔买入 `>=8,000 VIRTUAL` 卖原始总仓位 `50%`。
- 仅收益率达标、或仅出现大额买入，都不卖出。
- 状态来源：
  - 从 `launch_execution_ledger` 重建本程序买入收到的 token、已卖 token、已卖比例和冷却状态。
  - 每轮读取 burner 当前 token 余额，真实余额低于目标时按余额上限卖出。
  - 从实时 `events` 表读取 `--catch-up-events-sec` 窗口内的大额买入事件；只有成功卖出账本里的 `processedLargeBuyTxs` 会参与去重，避免在税率尚未进入 `<=30%` 时把大单提前标记为已处理。
- 广播门禁：service 内置 `VWR_ENABLE_AUTO_SELL_BROADCAST=1`，ExecStart 显式 `--mode broadcast --enable-broadcast`。
- 精确授权门禁：service 内置 `VWR_ENABLE_AUTO_SELL_APPROVE=1`，ExecStart 显式 `--auto-approve`；只有目标 token allowance 不足时，才精确授权本次卖出数量。
- 大额买入事件窗口：service 显式 `--catch-up-events-sec 120`，避免生产行为依赖脚本默认值。
- RPC：使用独立 execution Chainstack endpoint，默认拒绝共享主采集 RPC 广播。
- ROO 复盘修正：执行账本 `launch_execution_ledger` 在同一 intent 从 simulate 走到 broadcast/receipt 时，必须同步更新 `mode`，避免出现 `prewarm_simulate + trade_sent=1` 的审计假象。
- 失败处理：sell simulation、approve、sign、broadcast、receipt 任一异常写入 `launch_execution_ledger` 并触发 active fuse。
- 本地 smoke：TDS ended 项目 `autosell_simulate --once` 正常启动并返回 `no_position`，无签名、无广播。

### Stage 2.8：Live 发射档案与回测复用

- 目标：每个真实发射项目结束后，都能从生产只读数据生成一份可复用回测档案，后续策略回测不直接读生产 DB。
- 新增只读归档脚本：`scripts/ops/archive_launch_project.py`。
  - 输入：生产 SQLite、项目名/id、可选 sample JSONL。
  - 输出：`manifest.json`、`project.json`、`samples.jsonl`、`events.jsonl`、`execution-ledger.jsonl`、`fuses.jsonl`、`summary.json`、`archive.db`。
  - `summary.json` 暴露 `samplesPath/jsonlPath`，可直接作为回测入口。
- `live_strategy_dry_run.py` 新增 `--full-samples-jsonl`，用于每轮采样都写入独立 `launch-samples-<PROJECT>.jsonl`。
  - 生产事件日志仍保持 `state_change/heartbeat/intent` 口径，避免主日志膨胀。
  - 全量 samples 只由 dry-run/recorder 负责，autobuy/autosell 继续负责交易账本和 receipt，避免多进程重复写同一个样本文件。
- 新增生产只读 recorder 模板：`deploy/systemd/vwr-launch-dryrun@.service`。
  - 默认输出：`data/execution/live-strategy-dry-run-%i.jsonl`。
  - 全量采样：`data/execution/launch-samples-%i.jsonl`。
- 回测脚本入口泛化：
  - `scripts/ops/recalc_dynamic_buy_strategy.py --report <archive>/summary.json`。
  - `scripts/ops/recalc_dual_sell_strategy.py --report <archive>/summary.json --rule gate_5k_tax95_fdv_one_per_tax`。
- 本地 smoke：
  - `archive_launch_project.py --project TDS` 可从本地 DB 导出 `events / ledger / fuses / archive.db`。
  - 使用本地 prewarm smoke JSONL 指定 `--samples-jsonl` 后，可生成带 `samples.jsonl` 的归档。
  - 新的 `--report` 回测入口可读取归档 summary 并完成 dynamic/dual sell smoke。
- 2026-05-16 ROO live regression：
  - 报告：`docs/phases/phase-053-roo-live-regression-2026-05-16.md`。
  - 标准归档：`sampleCount=7993`、`eventCount=505`、`ledgerCount=240`、`warnings=[]`。
  - 买入 canonical 回放：当前主策略买入 `6` 次，总投入 `150 VIRTUAL`，最终收益率 `+31.8845%`。
  - 卖出 canonical 回放：触发 `1` 次卖出，最终收益率 `+32.7369%`，相对纯持有提升 `+0.846%`。
  - ROO live 期间 2 笔真实买入和 2 笔真实卖出 receipt 均复核为 `status=0x1`。

### Stage 2.9：通用 live 项目启动编排

- 问题：ROO 使用 `vwr-launch-roo-start.timer` 专用 timer，下一次项目不能继续手工复制 ROO 单项目启动文件。
- 新增通用编排脚本：`scripts/ops/schedule_launch_services.py`。
  - 输入：`--project <SYMBOL>` 与 `--start-at "YYYY-MM-DD HH:MM:SS"`。
  - 可选：`--auto-profile`，按官方 tax schedule 自动选择无税秒狙击或正常税率服务。
  - 默认在发射前 `35` 分钟启动 `dryrun / prewarm / autobuy / autosell`。
  - 默认按 `99` 分钟发射窗口 + `10` 分钟延迟创建归档 timer。
  - 默认只输出计划；只有显式 `--apply` 才写入 systemd unit 并执行 `systemctl daemon-reload / enable --now`。
  - 支持 `--start-now`，用于项目已进入 live 或临时补启服务。
- 新增本地 systemd prewarm 模板：`deploy/systemd/vwr-launch-prewarm@.service`，与生产现有模板对齐。
- 通用启动脚本会安装/刷新四个模板：
  - `vwr-launch-dryrun@.service`
  - `vwr-launch-prewarm@.service`
  - `vwr-launch-autobuy@.service`
  - `vwr-launch-autosell@.service`
- 通用启动脚本会生成项目级 unit：
  - `vwr-launch-<symbol>-start.service`
  - `vwr-launch-<symbol>-start.timer`
  - `vwr-launch-<symbol>-archive.service`
  - `vwr-launch-<symbol>-archive.timer`
- 验收脚本：`scripts/ops/test_schedule_launch_services.py`。

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
- ROO 开盘验证额度为 `0.1 VIRTUAL`。买入 receipt 成功后，应只卖出本次 receipt 的 `receiptTargetReceivedRaw`，不要使用 `amount-raw=max`，避免与自动买入策略并发时误卖策略仓位。
- Canary 与策略共享 burner，但不写入自动买入账本；验证结束后应立即卖出 canary token，避免后续 autosell 把 canary 余额当作可卖持仓处理。

### Stage 7：自动执行灰度

- 单项目白名单：通过 `--project` 指定，当前 ROO 单项目服务。
- 单笔上限：`--max-buy-v`，ROO 当前为 `50V`。
- 单项目上限：`--max-project-v`，ROO 当前为 `150V`。
- 项目级预算：生产 autobuy 模板使用 `--project-cap-scope project`，同一项目里普通买入、跟单买入、FDV 限价单会共同计入项目上限。
- 跟单策略：默认开启，仅 live 窗口生效；普通大户策略未出手时才评估跟单，跟单未出手时才进入 FDV 限价单。
- 同一税率档最多一次：执行器会读取 `launch_execution_ledger.trade_sent=1` 记录阻断重复广播。
- 重启恢复：执行器启动时从 `launch_execution_ledger.trade_sent=1` 重建已买税率、自有加权成本和上一税率买点，避免 systemd 重启后丢失 dip20 / 横盘暂停判断。
- `sign-ready/broadcast` 下任意 simulation/sign/prewarm/broadcast/receipt 异常熔断；`simulate` 只读模式只记账不熔断，避免灰度观察误挡真实执行。
- FDV 限价单例外：未广播前的 `simulation_not_green` 只代表当前链上条件暂不可买或报价短暂失效，应回到 pending 重试，不触发 active fuse；真实 broadcast / receipt 失败仍熔断。MTR 2026-05-21 出现过 `0xd4181deb` 后人工清 fuse 再成功成交，已作为该规则的回归案例。
- 自动卖出边界：生产常驻执行器已接入 ROO timer，但真实 live 窗口里的 SellIntent -> approval/simulation/broadcast/receipt 尚待第一次实盘验证。

## 6. 验收标准

- `StrategyEvaluator` 可在本地 replay 和实时 snapshot 两种来源下产生一致 BuyIntent。
- OrderBuilder 有真实历史交易 parity test。
- TxSimulator 能证明失败时不签名。
- LocalSigner 能证明签名但不广播。
- Broadcaster 默认拒绝广播。
- Canary 前必须有手动确认。
- 所有输出不包含私钥、seed、RPC token。
