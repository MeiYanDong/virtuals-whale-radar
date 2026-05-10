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
  - 当时 market snapshot。
  - 当时 overview / whale board snapshot。
  - 后续 `1m / 3m / 5m / 10m / end` 表现。

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
- 首次触发时间。
- 首次触发税率。
- 首次触发榜单 V。
- 首次触发含税 FDV。
- 首次触发榜单成本。
- 买入次数。
- 总投入。
- 最终收益率。
- `1m / 3m / 5m / 10m / end` 收益率。
- 最差回撤。
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
- 默认结算口径固定为 `1m / 3m / 5m / 10m / end`。

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
