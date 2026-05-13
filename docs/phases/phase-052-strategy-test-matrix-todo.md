# Phase 052 Strategy Test Matrix Todo

## 1. 文档冻结

- [x] 创建阶段子 plan：`docs/phases/phase-052-strategy-test-matrix-plan.md`。
- [x] 创建阶段子 todo：`docs/phases/phase-052-strategy-test-matrix-todo.md`。
- [x] 用户确认 Phase 052 的默认测试目标和风险边界。

## 2. 数据输入盘点

- [x] 列出本地和服务器已有 replay samples。
- [x] 确认 SR 高采样样本字段完整性。
- [x] 确认 ISC/TDS 对照样本字段完整性。
- [x] 定义后续真实项目 dry-run 日志格式。

## 3. 控制变量矩阵

- [x] 实现大户榜单 V 梯度。
- [x] 实现税率梯度。
- [x] 实现 FDV 成本折扣梯度。
- [x] 实现冷却时间梯度。
- [x] 实现连续买入限制梯度。
- [x] 实现最大项目投入梯度。
- [x] 实现最小榜单人数梯度。

## 4. 取消变量矩阵

- [x] 实现只看税率。
- [x] 实现只看榜单 V。
- [x] 实现只看 FDV 成本。
- [x] 实现榜单 V + 税率。
- [x] 实现榜单 V + FDV。
- [x] 实现税率 + FDV。
- [x] 实现榜单 V + 税率 + FDV。
- [x] 实现取消冷却。
- [x] 实现取消最大投入。
- [x] 实现取消最小榜单人数。

## 5. 多变量组合矩阵

- [x] 实现 `spent x tax`。
- [x] 实现 `spent x fdv_discount`。
- [x] 实现 `tax x fdv_discount`。
- [x] 实现 `spent x tax x fdv_discount`。
- [x] 实现 `cooldown x max_project_spend`。
- [x] 实现 `min_rows x spent`。
- [x] 实现 `burst_limit x cooldown`。

## 6. 场景模拟

- [x] 实现价格路径模拟。
- [x] 实现大户行为模拟。
- [x] 实现团队地址污染模拟。
- [x] 实现税率异常模拟。
- [x] 实现 RPC / 数据延迟模拟。
- [x] 实现执行层滑点和确认延迟模拟。

## 7. 统一报告

- [x] 输出 JSON 报告：`data/backtests/strategy-test-matrix-20260507.json`。
- [x] 输出 Markdown 报告：`docs/phases/phase-052-strategy-test-matrix-report.md`。
- [x] 输出 Top by final return。
- [x] 输出 Top by risk-adjusted score。
- [x] 输出 Stable zone。
- [x] 输出 Failure cases。
- [x] 输出 Variable contribution。
- [x] 输出 Overfit warning。
- [x] 输出 Dry-run candidates。
- [x] 输出 Reject list。
- [x] 追加硬门槛重筛：榜单人数 `20`、榜单 V `>= 50,000`、税率 `<= 95%`。

## 8. 验证

- [x] 用 SR 高采样样本跑完整矩阵。
- [x] 用 ISC 样本跑对照矩阵。
- [x] 用 TDS 样本跑对照矩阵。
- [x] 确认脚本只读 replay，不写生产 DB。
- [x] 确认报告不包含 RPC key、钱包私钥或 endpoint token。

## 9. 文档同步

- [x] 更新 `docs/plan-index.md`。
- [x] 更新 `docs/todo-index.md`。
- [x] 更新 `docs/PLAN.md` 阶段摘要。
- [x] 更新 `docs/todo.md` 阶段摘要。
- [x] 如需生产同步，更新 `scripts/ops/deploy_production_safe.sh` 白名单。

## 10. 2026-05-10 SR-only 口径修正

- [x] 撤回 `strategy-lab` 生产页面后，将策略实验重新限定为本地报告。
- [x] 明确旧 `14` 个候选是 `7` 条规则乘以 `2` 个 SR 采样数据集，不是 14 个独立策略。
- [x] 明确新事件模型：`pool_state_change + tax_tick + heartbeat`。
- [x] 明确 `pool_state_change` 必须覆盖 buy、sell、unknown pool event。
- [x] 明确 tax 变化瞬间即使没有交易也必须记录。
- [x] 明确收益评估只看 tax 降到 `1%` 的 end 表现，不再默认输出 `1m / 3m / 5m / 10m`。
- [x] 新增 SR-only 结果级重筛脚本：`scripts/ops/sr_strategy_recalc_from_matrix.py`。
- [x] 定位本地 RPC 根因：旧 `BACKFILL_*` Chainstack endpoint 优先导致历史块和 logs `403`，有效 endpoint 实际在 `HTTP_RPC_URL`。
- [x] 修复本地 `config.json` 的 backfill 顺序，改为有效 Chainstack endpoint 优先。
- [x] 修复本地 `SignalHub-main/.env` 的 Chainstack HTTPS 顺序，改为有效 Chainstack endpoint 优先。
- [x] 新增真正事件级 SR replay 脚本：`scripts/ops/sr_event_level_replay.py`。
- [x] 用 Chainstack 跑完 SR event-level replay：覆盖 buy、sell、unknown pool event、tax_tick、heartbeat。
- [x] 输出事件级报告：`docs/phases/phase-052-sr-event-level-replay-2026-05-10.md`。
- [x] 补充买入次数验证：`1089` 样本中只有 `25` 个满足硬条件，全部集中在一个短信号簇；当前 `60s + burst2 -> 10min` 执行限制将其压缩为 `2` 次买入。
- [x] 补充执行限制对照：`60s no burst = 4` 次、`30s no burst = 5` 次、`no cooldown max300 = 6` 次。
- [x] 明确税率更新时间锚点：SR 的 `startAt=1776049213`，北京时间 `11:00:13`，税率 tick 按 `startAt + n*60s` 更新，因此不是自然分钟整点。
- [x] 将 SR 策略榜单累计投入门槛从 `50,000 V` 降为 `5,000 V`。
- [x] 将执行限制从秒级冷却改为“同一税率档位最多买一次”。
- [x] 用现有 event-level 样本重算：最佳规则 `gate_5k_tax95_fdv_one_per_tax` 买入 `6` 次，投入 `300 V`，end 收益约 `+62.9736%`。
- [x] 只读检查生产服务器：确认 SWAS `Ubuntu-jsal` running，SSH `root + id_ed25519` 可用。
- [x] 只读检查主程序生产 RPC：加载后实际 backfill 顺序为 `Chainstack -> Ankr -> Alchemy -> mainnet.base.org`。
- [x] 只读检查 SignalHub 生产 RPC：systemd drop-in HTTPS 顺序为 `Chainstack -> Ankr -> Alchemy`，WSS 为 Chainstack。
- [x] 生产 Chainstack smoke 通过：`eth_blockNumber / SR historical block / SR 50 blocks logs` 均成功，约 `75-107ms`。
- [x] 生产健康检查通过：四个服务 active，`/healthz ok`，`/health ok=true`，`runtimePaused=false`。
- [x] 用 Chainstack 完成 ISC 完整 event-level replay：`600 tx / 322 buy / 41 sell / 237 unknown / 99 tax_tick / 1576 samples`。
- [x] 输出 ISC 事件级报告：`docs/phases/phase-052-isc-event-level-replay-2026-05-10.md`。
- [x] 输出 ISC tax tick 表：`data/backtests/isc-tax-ticks-20260510.csv`。
- [x] ISC `300 V` 上限结果：最佳 `gate_5k_tax89_fdv_one_per_tax`，买入 `6` 次，投入 `300 V`，end 收益约 `+114.548261 V / +38.1828%`。
- [x] ISC 不限制总投入结果：最佳收益率仍为 `tax<=89`，买入 `28` 次，投入 `1400 V`，end 收益约 `+542.59385 V / +38.7567%`。
- [x] 讨论并否掉“看到榜单 V 暴增 / FDV 快速反弹后再加仓”的后验确认策略：SR 中看到 `21k -> 127k` 时，低位机会已被重新定价。
- [x] 新增动态买入重算脚本：`scripts/ops/recalc_dynamic_buy_strategy.py`。
- [x] 确认当前采用策略：`25V` 基础买入，若当前含税 FDV 低于我方历史加权买入 FDV `20%` 以上则买 `50V`；某税率分钟买入后，下一税率分钟 FDV 相对上一买点变化 `<=10%` 则暂停一个税率档。
- [x] 用 SR/ISC 事件级样本重算 after1 动态策略：`data/backtests/dynamic-buy-recalc-after1-flat10-20260510.json`。
- [x] 输出 after1 动态策略报告：`docs/phases/phase-052-dynamic-buy-recalc-after1-flat10-2026-05-10.md`。
- [x] 保留 after2 对照报告：`docs/phases/phase-052-dynamic-buy-recalc-2026-05-10.md`。
- [x] 输出最终策略整理：`docs/phases/phase-052-final-dynamic-buy-strategy-2026-05-10.md`。
- [x] SR `tax<=95` 主规则结果：买入 `5` 次，投入 `125 V`，end 收益约 `+86.133020 V / +68.9064%`。
- [x] ISC ROI 最优 `tax<=89`：买入 `14` 次，投入 `350 V`，end 收益约 `+136.284025 V / +38.9383%`。
- [x] 明确 Phase 052 只冻结策略，交易执行链路进入 Phase 053。
- [x] 新增双策略自动卖出纯策略模块：`scripts/ops/launch_sell_strategy.py`。
- [x] 新增双策略自动卖出单元测试：`scripts/ops/test_launch_sell_strategy.py`。
- [x] 新增 SR/ISC 双策略卖出回测脚本：`scripts/ops/recalc_dual_sell_strategy.py`。
- [x] 输出双策略卖出回测报告：`docs/phases/phase-052-dual-sell-strategy-2026-05-11.md`。
- [x] 2026-05-13 根据 ROO live 修正卖出口径：税率 `<=30%` 后，大额买入必须由自身收益率确认；有效目标取收益率门槛和大额买入门槛的较低值。
- [x] 2026-05-13 修正回测事件窗口：与生产 autosell 一致，默认查看最近 `120 秒`内未处理的大额买入，而不是只看两个样本之间的事件。
- [x] 加固余额不足保护：真实余额低于目标卖出数量时，只按实际卖出的原始仓位比例更新策略状态。
- [x] 2026-05-13 新口径回测结果：SR 卖出 `1` 次，最终 `+58.0594%`，低于纯持有；ISC 不触发卖出，结果等同纯持有 `+38.9383%`。
- [x] Phase 053 已接入生产自动卖出执行链路：执行账本状态、真实余额读取、sell simulation、精确 token approve、broadcast gate、receipt/fuse。
