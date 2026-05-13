# Phase 052 Strategy Test Matrix Plan

## 1. 目标

建立一套可复用的多维度策略测试矩阵。后续任何自动买入策略变更，都必须先通过这套测试，再进入 realtime dry-run；真实交易路径不在本阶段启用。

## 2. 非目标

- 不接热钱包。
- 不发真实交易。
- 不写生产数据库。
- 不把单个历史项目的最高收益当作上线依据。

## 3. 输入数据

- 历史 replay samples：
  - SR 高采样完整窗口。
  - SR 144-sample 完整窗口。
  - ISC 早段 replay。
  - ISC 完整窗口或后续可用完整窗口。
  - TDS 完整窗口。
- 后续真实项目 dry-run 日志：
  - would-buy signal。
  - 触发来源：`pool_state_change / tax_tick / heartbeat`。
  - `pool_state_change` 必须覆盖 buy、sell，以及无法立即归类但可能改变池子价格的 unknown pool event。
  - 当时 market snapshot。
  - 当时 overview / whale board snapshot。
  - 只记录 tax 降到 `1%` 的 end 表现；不再把 `1m / 3m / 5m / 10m` 作为默认评估口径。

## 4. 测试维度

### 4.1 单变量梯度

- 大户榜单 V 门槛：`0-200k`，重点 `50k-120k` 每 `10k` 一档。
- 税率门槛：`99-80`，重点 `95 / 94 / 93 / 92 / 91 / 90`。
- FDV 成本折扣：`none / 1 / 0.99 / 0.98 / 0.95 / 0.9`。
- 冷却时间：`0 / 30 / 60 / 120 / 180 / 300 / 600s`。
- 连续买入限制：不限制、2 次、3 次。
- 最大项目投入：`50 / 100 / 150 / 300 / 500 / 1000V`。
- 最小榜单人数：`0 / 1 / 3 / 5 / 10 / 15 / 20`。

### 4.2 取消变量测试

- 只看税率。
- 只看榜单 V。
- 只看 FDV 成本。
- 榜单 V + 税率。
- 榜单 V + FDV。
- 税率 + FDV。
- 榜单 V + 税率 + FDV。
- 取消冷却。
- 取消最大投入。
- 取消最小榜单人数。

### 4.3 多变量组合

- `spent x tax`。
- `spent x fdv_discount`。
- `tax x fdv_discount`。
- `spent x tax x fdv_discount`。
- `cooldown x max_project_spend`。
- `min_rows x spent`。
- `burst_limit x cooldown`。

### 4.4 数据形态模拟

- 一路上涨。
- 一路下跌。
- 前期上涨后横盘。
- 前期上涨后后段砸盘。
- 前期横盘后突然拉升。
- 高波动震荡。
- 买入后 1 分钟内快速回撤。
- 大户早期集中打入。
- 大户慢速打入。
- 大户后段突然加速。
- 一个巨鲸主导榜单。
- 多个中等钱包均匀买入。
- 团队低成本地址未排除。
- 团队地址被正确排除。
- 榜一异常大额污染加权成本。

### 4.5 税率与数据异常

- 98min 税率。
- 60s 税率。
- 官网自定义税率。
- 税率字段缺失。
- 税率预测错误。
- 链上税率证据与官网不一致。
- 税率跳变。
- price / overview / logs / receipt 延迟。
- WSS 断线恢复。
- RPC 返回旧 block 或缺 block。

### 4.6 执行层模拟

- 入口滑点：`0.5% / 1% / 3% / 5% / 10%`。
- 交易确认延迟：`1 / 2 / 5 blocks`。
- 买入失败。
- receipt 延迟。
- 上一笔未确认时再次触发。
- gas 突增。
- 余额不足。
- 单项目预算用完。
- 冷却期间继续出现信号。

## 5. 输出指标

每个 case 必须输出：

- 是否触发。
- 触发来源：`buy / sell / tax_tick / heartbeat / unknown_pool_event`。
- 首次触发时间。
- 首次触发税率。
- 首次触发榜单 V。
- 首次触发含税 FDV。
- 首次触发榜单成本。
- 买入次数。
- 总投入。
- tax 降到 `1%` 时的 end 收益率。
- tax 降到 `1%` 时的 end PnL。
- 是否买满。
- 是否依赖极少数榜单样本。
- 触发失败原因统计。

## 6. 报告结构

统一报告必须包含：

- Top by final return。
- Top by risk-adjusted score。
- Stable zone。
- Failure cases。
- Variable contribution。
- Overfit warning。
- Dry-run candidates。
- Reject list。

## 7. 验收标准

- 能一键跑完 SR 控制变量矩阵。
- 能一键跑完 SR 多维度压力测试。
- 能把 ISC/TDS 作为对照项目纳入同一报告。
- 能输出机器可读 JSON 和人可读 Markdown。
- 不触碰生产 DB，不发交易，不读取或写入 secret。
- 报告能明确推荐进入 realtime dry-run 的候选策略和明确拒绝的策略。

## 8. 默认策略候选

- Conservative: `100k + tax<=92 + fdv`。
- Mid: `70k / 80k / 90k + tax<=95 + fdv`。
- Aggressive: `50k + tax<=95/94/93 + fdv`。
- Control: `tax_only` 与 `tax+fdv no spent limit`，只做对照，不直接交易。

## 9. 执行默认值

- 优化目标固定为“稳定盈利 + 低误触发”，不以单次最高收益作为上线依据。
- dry-run 模拟最大项目预算固定为 `300V`。
- 交易候选硬门槛：
  - 大户榜单人数必须满 `20`。
  - 大户榜单累计投入必须 `>= 50,000 V`。
  - 税率必须已经降到 `<= 95%`。
- 成本样本少于 `5` 时只记录风险，不进入 dry-run 候选。
- 默认结算口径固定为 tax 降到 `1%` 时的 end 表现。
- 策略触发事件模型固定为：
  - `pool_state_change`：buy、sell、unknown pool event，只要可能改变池子价格就必须记录。
  - `tax_tick`：税率变化瞬间，即使没有交易、代币价格不变，也必须记录，因为含税 FDV 会变化。
  - `heartbeat`：低频兜底点，只用于补漏和延迟审计，不替代前两类事件。

## 10. 2026-05-07 验收结果

- 已新增统一 runner：`scripts/ops/strategy_test_matrix_runner.py`。
- 已在服务器使用 Chainstack replay 样本跑完整矩阵：
  - SR 高采样完整窗口。
  - SR 144-sample 完整窗口。
  - ISC Chainstack suite 10 分钟样本。
  - TDS 完整窗口样本。
- 输出报告：
  - Markdown：`docs/phases/phase-052-strategy-test-matrix-report.md`。
  - JSON：`data/backtests/strategy-test-matrix-20260507.json`。
- 覆盖规模：
  - `737` 条规则。
  - `34` 类场景。
  - `4,136` 个结果。
- 当前可进入 dry-run 观察的候选：
  - `conservative_100k_tax92_fdv`。
  - `mid_70k_tax95_fdv / mid_80k_tax95_fdv / mid_90k_tax95_fdv`。
  - `aggressive_50k_tax95_fdv / aggressive_50k_tax94_fdv / aggressive_50k_tax93_fdv`。
- 2026-05-07 追加硬门槛重筛：
  - `whaleRows >= 20`。
  - `boardSpentV >= 50,000`。
  - `buyTaxRate <= 95`。
  - SR 仍保留 `14` 个 dry-run 候选；ISC / TDS 当前无 dry-run 候选。
- 明确不能直接进入交易候选的对照：
  - tax-only。
  - no-FDV-cost。
  - no-board-spent。
  - low-sample first-buy。
  - high-latency / high-slippage / tax-signal anomaly 场景。

## 11. 2026-05-10 SR-only 口径修正

- `strategy-lab` 页面已撤回生产主线；策略实验只作为本地工具和文档报告存在。
- 旧报告的 `14` 个 SR 候选不能理解为 14 个独立策略；它主要是 `7` 条规则乘以 `2` 个 SR 采样数据集。
- 重新计算范围先收窄为 SR-only：
  - 主样本：`sr_chainstack_highres_strategy`。
  - `sr_chainstack_full-20260507T080007Z` 只作为低频采样交叉验证，不能当作独立 Alpha 证据。
- 最新测试模型修正：
  - 事件源不能只看 buy，必须覆盖 sell 和 unknown pool event。
  - 税率变化瞬间必须作为一等 `tax_tick` 事件，即使没有交易。
  - 收益评估只看 tax 降到 `1%` 的 end 表现，不再默认计算 `1m / 3m / 5m / 10m`。
- 本地 SR-only 重筛只是结果级重筛，读取既有矩阵 JSON；真正事件级 SR replay 已在下一节补完。

## 12. 2026-05-10 RPC 修复与 SR event-level replay

- RPC 根因：
  - 本地 `HTTP_RPC_URL` 指向的 Base Chainstack 节点可用，已验证支持 SR 历史块和 SR 小窗口 `eth_getLogs`。
  - 旧 `BACKFILL_HTTP_RPC_URL / BACKFILL_HTTP_RPC_URLS` 优先指向已不可用或无权限的旧 endpoint，导致历史块和 logs 返回 `403`。
  - 本地 `SignalHub-main/.env` 也存在同样顺序问题，旧 HTTPS endpoint 排在有效 Chainstack 节点前面。
- 本地运行态修复：
  - `config.json` 的 `BACKFILL_HTTP_RPC_URL` 与 `BACKFILL_HTTP_RPC_URLS` 已改为有效 Chainstack endpoint 优先。
  - `SignalHub-main/.env` 的 `CHAINSTACK_BASE_HTTPS_URL / CHAINSTACK_BASE_HTTPS_URLS` 已改为有效 Chainstack endpoint 优先。
  - 文档不记录 endpoint token。
- 新增事件级 replay：
  - 脚本：`scripts/ops/sr_event_level_replay.py`。
  - 报告：`docs/phases/phase-052-sr-event-level-replay-2026-05-10.md`。
  - JSON：`data/backtests/sr-event-level-replay-20260510T073102Z.json`。
- SR event-level replay 已用 Chainstack 完成：
  - `txCount = 751`。
  - `poolEventCount = 751`。
  - `buy = 601`。
  - `sell = 24`。
  - `unknown_pool_event = 126`。
  - `taxTickCount = 99`。
  - `sampleCount = 1089`。
  - `parsedBuyEventCount = insertedBuyEventCount = 601`。
- 当前最佳候选仍为 `aggressive_50k_tax95/94/93_fdv`：
  - 首买：`tax=93 / board=54,166.025 V / 含税 FDV=259.120641 万 USD / 榜单成本=312.570139 万 USD / costPos=2/19`。
  - 投入 `100 V`，end 收益约 `+57.7737%`。
- 对买入次数做过验证：
  - `1089` 个样本里，满足硬条件的信号样本只有 `25` 个。
  - 这 `25` 个信号全部集中在一个短信号簇：`1776049593 -> 1776049815`，tax 从 `93` 到 `89`。
  - 当前策略执行层是 `60s` 冷却 + `120s` 内连续 `2` 次后冷却 `10min`，因此实际只买 `2` 次，另外 `23` 个信号样本被 cooldown 拦截。
  - 对照验证：关闭 burst 限制但保留 `60s` 冷却会买 `4` 次；`30s` 冷却无 burst 会买 `5` 次；无冷却但保留 `300 V` 最大投入会买 `6` 次。
  - 因此“样本量增加但买入次数不增加”不是漏采，而是当前执行规则把同一短窗口信号压缩成 `2` 次买入。
- 2026-05-10 策略门槛修正：
  - 税率更新时间不是自然整点，而是以官网 `launchedAt` 为锚点；SR 的 `startAt=1776049213`，北京时间 `11:00:13`，所以 98 分钟税率 tick 都落在 `:13`。
  - 榜单累计投入门槛从 `50,000 V` 降为 `5,000 V`。
  - 执行限制从 `60s cooldown + 120s burst cooldown` 改为“同一税率档位最多买一次”。
  - 用现有 `1089` 个 event-level 样本重算后，最佳规则 `gate_5k_tax95_fdv_one_per_tax` 买入 `6` 次，投入 `300 V`，end 收益约 `+62.9736%`。
  - 新买点覆盖 tax `95 / 94 / 93 / 92 / 91 / 90`；tax `89` 仍是信号，但被 `300 V` 项目最大投入限制拦截。

## 13. 2026-05-10 生产 RPC 只读检查

- 服务器确认：
  - 类型：阿里云轻量应用服务器 SWAS，不是 ECS。
  - 实例：`Ubuntu-jsal`，公网 `47.243.172.165`，状态 `Running`。
  - 项目目录：`/opt/virtuals-whale-radar`。
- SSH 确认：
  - `root + ~/.ssh/id_ed25519` 可登录。
  - 其他常见用户/key 组合未通过，不作为当前项目主登录方式。
- 线上主程序 RPC 运行态：
  - `vwr@writer / vwr@realtime / vwr@backfill` 通过 `/etc/virtuals-whale-radar/rpc.env` 注入环境变量。
  - `config.json` 使用 `${CHAINSTACK_BASE_HTTP_RPC_URL}` 等占位，加载后实际 backfill 顺序为：`Chainstack -> Ankr -> Alchemy -> mainnet.base.org`。
  - `BACKFILL_PUBLIC_HTTP_RPC_URLS` 保留 `mainnet.base.org / publicnode`，但只是公开兜底，不是主路径。
- 线上 SignalHub RPC 运行态：
  - `vwr-signalhub.service` 通过 `/etc/virtuals-whale-radar/signalhub-rpc.env` 注入环境变量。
  - SignalHub 加载后 HTTPS 顺序为：`Chainstack -> Ankr -> Alchemy`；WSS 为 Chainstack。
  - `SignalHub-main/.env` 中存在历史 endpoint，但 `signalhub.app.config` 不会覆盖已存在的 systemd 环境变量，因此当前生产服务以 drop-in env 为准。
- Chainstack smoke：
  - `eth_blockNumber`：约 `107ms`。
  - SR 历史 block：约 `78ms`。
  - SR 50 blocks logs：约 `75ms`。
- 健康状态：
  - `vwr-signalhub.service / vwr@writer / vwr@realtime / vwr@backfill` 均为 `active`。
  - `SignalHub /healthz = ok`。
  - 主程序 `/health ok = true`，`runtimePaused = false`，`ws_connected = true`。

## 14. 2026-05-10 ISC event-level replay

- 测试目标：
  - 项目：ISC / Isaac Protocol。
  - Virtuals ID：`72752`。
  - 范围：完整 tax-end 发射窗口，不是此前 10 分钟样本。
  - RPC：Chainstack。
  - 策略口径：`榜单V >= 5,000`、`FDV <= 榜单成本`、`同一税率档位最多买一次`、每次 `50 V`。
- 数据规模：
  - `600 tx`。
  - `322 buy`。
  - `41 sell`。
  - `237 unknown_pool_event`。
  - `99 tax_tick`。
  - `1576 samples`。
  - `logErrors = 0`。
- `300 V` 上限结果：
  - 最佳规则：`gate_5k_tax89_fdv_one_per_tax`。
  - 买入 `6` 次，投入 `300 V`。
  - end 收益约 `+114.548261 V / +38.1828%`。
  - 买入税率覆盖 `89 -> 84`。
- 不限制总投入结果：
  - 最佳收益率规则仍为 `gate_5k_tax89_fdv_one_per_tax`。
  - 买入 `28` 次，投入 `1400 V`。
  - end 收益约 `+542.59385 V / +38.7567%`。
  - 买入税率覆盖 `89 -> 54`。
  - 绝对收益最高的是 `gate_5k_tax95_fdv_one_per_tax`，买入 `32` 次，投入 `1600 V`，end 收益约 `+586.593695 V`，但收益率降至约 `+36.6621%`。
- 结论：
  - ISC 与 SR 不同，最佳触发不在高税率 95/94/93，而是从 `89%` 开始。
  - 早启动会增加绝对买入次数，但会拉低平均收益率。
  - 当前硬条件下，ISC 的信号主要集中在 `89 -> 66` 与 `57 -> 54` 两段；中间有一段被 `FDV > 榜单成本` 排除。

## 15. 2026-05-10 最终动态买入策略口径

- 最终整理文档：`docs/phases/phase-052-final-dynamic-buy-strategy-2026-05-10.md`。
- 动态策略重算报告：`docs/phases/phase-052-dynamic-buy-recalc-after1-flat10-2026-05-10.md`。
- after2 对照报告：`docs/phases/phase-052-dynamic-buy-recalc-2026-05-10.md`。
- 重算脚本：`scripts/ops/recalc_dynamic_buy_strategy.py`。
- 当前采用策略：`dynamic_25v_dip20_after1_flat10_no_cap`。
- 硬条件：
  - `boardSpentV >= 5,000 V`。
  - `whaleRows >= 20`。
  - `costRows >= 5`。
  - `estimatedFdvWanUsdWithTax <= boardCostWanUsd`。
  - 同一税率档位最多买一次。
- 买入数量：
  - 默认 `25 VIRTUAL`。
  - 若当前含税 FDV `<= 我方历史加权买入 FDV * 0.8`，本次买入 `50 VIRTUAL`。
  - 本轮 SR/ISC 回测中 `50V` 条件均未触发。
- 暂停规则：
  - 某税率分钟买入后，如果下一个税率分钟的含税 FDV 相比上一笔买入变化 `<=10%`，跳过该税率分钟。
  - 再下一个税率分钟重新开始计算。
- 当前策略回测结果：
  - SR `tax<=95`：买入 `5` 次，投入 `125 V`，end 收益 `+86.133020 V / +68.9064%`。
  - SR ROI 最优 `tax<=94`：买入 `4` 次，投入 `100 V`，end 收益 `+71.463410 V / +71.4634%`。
  - ISC ROI 最优 `tax<=89`：买入 `14` 次，投入 `350 V`，end 收益 `+136.284025 V / +38.9383%`。
  - ISC 绝对收益最高 `tax<=95`：买入 `17` 次，投入 `425 V`，end 收益 `+149.391990 V / +35.1511%`。
- 明确否掉的策略：
  - 看到榜单 V 暴增或 FDV 快速反弹后再加仓：这是事后确认，SR 低位机会已消失，不能作为前置信号。
  - 固定 `50V` 且不限制总投入：只作为压力测试，不作为生产候选。
  - after2 横盘暂停：绝对收益更高，但总投入和资金占用更大；当前先采用风险更低的 after1。
- 当前边界：
  - 策略验证进入 Phase 053 执行链路。
  - 后续需要依次测试 realtime dry-run、OrderBuilder、TxSimulator、LocalSigner、小额 canary 和灰度广播。

## 16. 2026-05-11 双策略自动卖出口径

- 新增纯策略模块：`scripts/ops/launch_sell_strategy.py`。
- 新增策略测试：`scripts/ops/test_launch_sell_strategy.py`。
- 新增 SR/ISC 回测脚本：`scripts/ops/recalc_dual_sell_strategy.py`。
- 输出回测报告：`docs/phases/phase-052-dual-sell-strategy-2026-05-11.md`。
- 策略口径：
  - 2026-05-13 根据 ROO live 结果修正：大额买入必须由自身收益率确认后才触发卖出，后续若接生产必须继续走 Phase 053 执行门禁。
  - 进入卖出观察：税率 `<=30%`。
  - 收益率门槛：我的收益率 `>=30%` 对应 `30%`，`>=50%` 对应 `50%`。
  - 大额买入门槛：单笔买入 `>=5,000 VIRTUAL` 对应 `30%`，`>=8,000 VIRTUAL` 对应 `50%`。
  - 有效卖出目标取收益率门槛和大额买入门槛的较低值；仅收益率达标或仅大额买入都不卖出。
  - 回测脚本已对齐生产执行器的大额买入事件窗口：默认查看最近 `120 秒`内未处理的大额买入。
  - 程序按原始累计收到 token 数量计算卖出比例，避免按当前余额重复折扣。
  - 若真实余额低于目标卖出数量，只按实际卖出的原始仓位比例更新策略状态，避免误记已卖额度。
- SR/ISC 回测结果：
  - 2026-05-13 新口径回测：SR 卖出 `1` 次，最终 `+72.574207 V / +58.0594%`，低于纯持有 `+68.9064%`。
  - 2026-05-13 新口径回测：ISC 不触发卖出，结果等同纯持有 `+38.9383%`。
- 当前边界：
  - 策略决策、历史回测和生产自动卖出执行链路已完成。
  - 真实 live 窗口 SellIntent -> approval/simulation/broadcast/receipt 仍需继续用后续项目验证。
