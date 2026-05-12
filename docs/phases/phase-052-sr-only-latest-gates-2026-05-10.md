# SR 最新门槛结果级重筛

本报告只读取既有 `strategy-test-matrix-20260507.json` 中的 SR result rows，未重新抓链、未重放 tx、未重建样本、未包含 ISC/TDS。

> 本轮是结果级重筛，不是完整事件级 replay。源矩阵没有重建 sell、unknown pool event、tax_tick 和 heartbeat 时间线。

## 口径
- 主样本：`sr_chainstack_highres_strategy`。
- 交叉验证样本：`sr_chainstack_full-20260507T080007Z`。
- 候选只看 `actual` 场景；压力/合成/价格路径场景不进入候选排序。
- 硬门槛：榜单人数 `>=20`、成本样本 `>=5`、榜单累计投入 `>=50,000 V`、税率 `0-95%`、规则本身必须包含榜单 V 门槛、税率门槛和 FDV 成本保护。
- 完整事件模型应为 `pool_state_change + tax_tick + heartbeat`，其中 `pool_state_change` 覆盖 buy、sell、unknown pool event。
- 收益只看 tax 降到 `1%` 的 end 表现；`1m / 3m / 5m / 10m` 不再作为默认指标。
- 本结果级重筛使用矩阵里的 `finalPnlPct / finalPnlV` 作为 end 表现代理；仍然只是 realtime dry-run 候选，不是自动买入开关。

## 当前执行限制
- The source matrix stores buy entries and final sample PnL; it does not reconstruct sell/tax_tick/unknown event trigger points.
- This run treats finalPnlPct/finalPnlV from the matrix as the end performance proxy.
- A full precision SR replay still requires rebuilding the event timeline from pool_state_change + tax_tick + heartbeat.

## 不重新计算的数据
- chain replay
- sample extraction
- sell event timeline
- unknown pool event timeline
- tax_tick timeline
- heartbeat timeline
- token price path
- whale board aggregation
- ISC/TDS rows
- strategy-lab UI derived metrics
- synthetic scenario generation

## 数据规模
| source results | SR rows | SR actual rows | primary actual | validation actual | candidate rows | unique rules | primary entry clusters |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4136 | 2068 | 1474 | 737 | 737 | 14 | 7 | 3 |

## 主样本实际入场簇
| 入场簇 | 覆盖规则 | 买入次数 | 投入 | end收益 | 首买 |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | aggressive_50k_tax95_fdv, aggressive_50k_tax94_fdv, aggressive_50k_tax93_fdv | 2 | 100 | 59.4671% | tax 93, board 54966V, FDV 276.15万, cost 331.38万, costPos 2/19 |
| 2 | mid_70k_tax95_fdv, mid_80k_tax95_fdv, mid_90k_tax95_fdv | 2 | 100 | 42.1103% | tax 93, board 98430V, FDV 340.43万, cost 341.68万, costPos 11/19 |
| 3 | conservative_100k_tax92_fdv | 2 | 100 | 38.0501% | tax 92, board 132032V, FDV 359.71万, cost 364.64万, costPos 8/19 |

## 候选规则
| Rule | 主样本买入 | 主样本end收益 | 主样本首买 | 验证样本买入 | 验证样本end收益 | 验证样本首买 |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| aggressive_50k_tax93_fdv | 2 | 59.4671% | tax 93, board 54966V, FDV 276.15万, cost 331.38万, costPos 2/19 | 1 | 40.4541% | tax 90, board 164791V, FDV 368.66万, cost 388.27万, costPos 6/19 |
| aggressive_50k_tax94_fdv | 2 | 59.4671% | tax 93, board 54966V, FDV 276.15万, cost 331.38万, costPos 2/19 | 1 | 40.4541% | tax 90, board 164791V, FDV 368.66万, cost 388.27万, costPos 6/19 |
| aggressive_50k_tax95_fdv | 2 | 59.4671% | tax 93, board 54966V, FDV 276.15万, cost 331.38万, costPos 2/19 | 1 | 40.4541% | tax 90, board 164791V, FDV 368.66万, cost 388.27万, costPos 6/19 |
| conservative_100k_tax92_fdv | 2 | 38.0501% | tax 92, board 132032V, FDV 359.71万, cost 364.64万, costPos 8/19 | 1 | 40.4541% | tax 90, board 164791V, FDV 368.66万, cost 388.27万, costPos 6/19 |
| mid_70k_tax95_fdv | 2 | 42.1103% | tax 93, board 98430V, FDV 340.43万, cost 341.68万, costPos 11/19 | 1 | 40.4541% | tax 90, board 164791V, FDV 368.66万, cost 388.27万, costPos 6/19 |
| mid_80k_tax95_fdv | 2 | 42.1103% | tax 93, board 98430V, FDV 340.43万, cost 341.68万, costPos 11/19 | 1 | 40.4541% | tax 90, board 164791V, FDV 368.66万, cost 388.27万, costPos 6/19 |
| mid_90k_tax95_fdv | 2 | 42.1103% | tax 93, board 98430V, FDV 340.43万, cost 341.68万, costPos 11/19 | 1 | 40.4541% | tax 90, board 164791V, FDV 368.66万, cost 388.27万, costPos 6/19 |

## 关键解释
- 旧口径的 `14` 个候选不应理解为 14 个独立策略；它主要是 7 条规则乘以 2 个 SR 采样数据集。
- 高频 SR 主样本显示 `50k tax<=93/94/95 fdv` 的首买更早，历史收益更高；但它仍是单个历史项目结果，只能进入 would-buy 观察。
- 144-sample 验证样本由于采样更粗，所有候选首买都延后到 `tax=90 / boardSpentV≈164k`，只能说明低频采样会错过早期触发点，不能当作独立 Alpha 证据。
- 真正下一版 SR replay 必须补入 sell、unknown pool event 和 tax_tick；否则触发时间仍可能系统性延后。

## 主样本对照项，不作为候选
| Rule | Buys | End PnL | First buy | Reject reason |
| --- | ---: | ---: | --- | --- |
| control_tax95_fdv_no_spent | 2 | 77.7627% | tax 95, board 8193V, FDV 309.53万, cost 535.73万, costPos 1/13 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, critical_risk_flags:no_board_spent_guard, buy1_whale_rows_lt_20, buy1_board_spent_lt_50000, buy2_board_spent_lt_50000 |
| control_tax_only_95 | 6 | 28.6425% | tax 95, board 8193V, FDV 309.53万, cost 535.73万, costPos 1/13 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, missing_fdv_cost_guard, critical_risk_flags:no_board_spent_guard,no_fdv_cost_guard, buy1_whale_rows_lt_20, buy1_board_spent_lt_50000, buy2_board_spent_lt_50000 |
| only_fdv | 2 | 32.1403% | tax 97, board 1055V, FDV 506.2万, cost 796.38万, costPos 1/7 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, missing_or_loose_tax_guard, critical_risk_flags:no_board_spent_guard, buy1_whale_rows_lt_20, buy1_board_spent_lt_50000, buy1_tax_not_lte_95, buy2_whale_rows_lt_20, buy2_board_spent_lt_50000 |
| only_spent100k | 6 | 9.3104% | tax 93, board 107986V, FDV 360.47万, cost 347.43万, costPos 10/19 | not_dry_run_candidate_suite, missing_or_loose_tax_guard, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| only_tax92 | 6 | 12.441% | tax 92, board 132032V, FDV 359.71万, cost 364.64万, costPos 8/19 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, missing_fdv_cost_guard, critical_risk_flags:no_board_spent_guard,no_fdv_cost_guard |
| only_tax95 | 6 | 28.6425% | tax 95, board 8193V, FDV 309.53万, cost 535.73万, costPos 1/13 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, missing_fdv_cost_guard, critical_risk_flags:no_board_spent_guard,no_fdv_cost_guard, buy1_whale_rows_lt_20, buy1_board_spent_lt_50000, buy2_board_spent_lt_50000 |
| spent=0\|tax<=90\|no_fdv | 6 | 11.1551% | tax 90, board 164791V, FDV 362.48万, cost 380.64万, costPos 6/19 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=0\|tax<=91\|no_fdv | 6 | 13.0862% | tax 91, board 159225V, FDV 375.72万, cost 377.85万, costPos 8/19 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=0\|tax<=92\|no_fdv | 6 | 12.441% | tax 92, board 132032V, FDV 359.71万, cost 364.64万, costPos 8/19 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=0\|tax<=93\|no_fdv | 6 | 28.268% | tax 93, board 21211V, FDV 232.71万, cost 409.27万, costPos 1/19 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard, buy1_board_spent_lt_50000 |
| spent=0\|tax<=94\|no_fdv | 6 | 36.5159% | tax 94, board 16014V, FDV 265.04万, cost 456.15万, costPos 1/19 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard, buy1_board_spent_lt_50000, buy2_board_spent_lt_50000 |
| spent=0\|tax<=95\|no_fdv | 6 | 28.6425% | tax 95, board 8193V, FDV 309.53万, cost 535.73万, costPos 1/13 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard, buy1_whale_rows_lt_20, buy1_board_spent_lt_50000, buy2_board_spent_lt_50000 |
| spent=100000\|tax<=90\|no_fdv | 6 | 11.1551% | tax 90, board 164791V, FDV 362.48万, cost 380.64万, costPos 6/19 | not_dry_run_candidate_suite, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=100000\|tax<=91\|no_fdv | 6 | 13.0862% | tax 91, board 159225V, FDV 375.72万, cost 377.85万, costPos 8/19 | not_dry_run_candidate_suite, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=100000\|tax<=92\|no_fdv | 6 | 12.441% | tax 92, board 132032V, FDV 359.71万, cost 364.64万, costPos 8/19 | not_dry_run_candidate_suite, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=100000\|tax<=93\|no_fdv | 6 | 9.3104% | tax 93, board 107986V, FDV 360.47万, cost 347.43万, costPos 10/19 | not_dry_run_candidate_suite, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=100000\|tax<=94\|no_fdv | 6 | 9.3104% | tax 93, board 107986V, FDV 360.47万, cost 347.43万, costPos 10/19 | not_dry_run_candidate_suite, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=100000\|tax<=95\|no_fdv | 6 | 9.3104% | tax 93, board 107986V, FDV 360.47万, cost 347.43万, costPos 10/19 | not_dry_run_candidate_suite, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=10000\|tax<=90\|no_fdv | 6 | 11.1551% | tax 90, board 164791V, FDV 362.48万, cost 380.64万, costPos 6/19 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=10000\|tax<=91\|no_fdv | 6 | 13.0862% | tax 91, board 159225V, FDV 375.72万, cost 377.85万, costPos 8/19 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=10000\|tax<=92\|no_fdv | 6 | 12.441% | tax 92, board 132032V, FDV 359.71万, cost 364.64万, costPos 8/19 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=10000\|tax<=93\|no_fdv | 6 | 28.268% | tax 93, board 21211V, FDV 232.71万, cost 409.27万, costPos 1/19 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard, buy1_board_spent_lt_50000 |
| spent=10000\|tax<=94\|no_fdv | 6 | 36.5159% | tax 94, board 16014V, FDV 265.04万, cost 456.15万, costPos 1/19 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard, buy1_board_spent_lt_50000, buy2_board_spent_lt_50000 |
| spent=10000\|tax<=95\|no_fdv | 6 | 23.7924% | tax 95, board 13513V, FDV 315.3万, cost 469.39万, costPos 1/17 | not_dry_run_candidate_suite, missing_or_low_board_spent_guard, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard, buy1_whale_rows_lt_20, buy1_board_spent_lt_50000, buy2_board_spent_lt_50000 |
| spent=110000\|tax<=90\|no_fdv | 6 | 11.1551% | tax 90, board 164791V, FDV 362.48万, cost 380.64万, costPos 6/19 | not_dry_run_candidate_suite, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=110000\|tax<=91\|no_fdv | 6 | 13.0862% | tax 91, board 159225V, FDV 375.72万, cost 377.85万, costPos 8/19 | not_dry_run_candidate_suite, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=110000\|tax<=92\|no_fdv | 6 | 12.441% | tax 92, board 132032V, FDV 359.71万, cost 364.64万, costPos 8/19 | not_dry_run_candidate_suite, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=110000\|tax<=93\|no_fdv | 6 | 9.4219% | tax 93, board 127032V, FDV 397.66万, cost 361.34万, costPos 13/19 | not_dry_run_candidate_suite, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=110000\|tax<=94\|no_fdv | 6 | 9.4219% | tax 93, board 127032V, FDV 397.66万, cost 361.34万, costPos 13/19 | not_dry_run_candidate_suite, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
| spent=110000\|tax<=95\|no_fdv | 6 | 9.4219% | tax 93, board 127032V, FDV 397.66万, cost 361.34万, costPos 13/19 | not_dry_run_candidate_suite, missing_fdv_cost_guard, critical_risk_flags:no_fdv_cost_guard |
