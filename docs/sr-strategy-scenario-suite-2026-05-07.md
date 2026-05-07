# SR 策略梯度与场景压力测试

本报告只读 replay 样本，不写生产数据库，不发交易。

## 样本
- sampleCount: 1034
- firstTimestamp: 1776049216
- lastTimestamp: 1776055153
- durationSec: 5937
- taxMin: 1
- taxMax: 99
- boardSpentMaxV: 315347.598
- boardCostMaxWanUsd: 1515.970123
- boardCostMinWanUsd: 329.876022

## 单参数梯度摘要
| 维度 | 测试数量 | 触发数量 | 平均收益率 | 中位收益率 | 最差收益率 | 最好收益率 | 最佳 case |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| spent_threshold | 35 | 17 | 37.86 | 38.0501 | 33.7736 | 40.0431 | 160000 |
| tax_threshold | 50 | 11 | 37.7994 | 38.0501 | 33.7736 | 40.0431 | 90 |
| fdv_discount | 26 | 5 | 39.7522 | 40.0431 | 38.0501 | 40.5818 | 0.98 |
| cooldown | 9 | 9 | 39.9359 | 40.5818 | 38.0501 | 41.1205 | 180 |
| burst_limit | 4 | 4 | 38.476 | 38.618 | 38.0501 | 38.618 | 0 |
| max_project_spend | 7 | 7 | 38.4887 | 38.0501 | 38.0501 | 41.1205 | 50 |
| min_rows | 6 | 5 | 38.0501 | 38.0501 | 38.0501 | 38.0501 | 1 |
| base | 1 | 1 | 38.0501 | 38.0501 | 38.0501 | 38.0501 | base |

## 二维组合梯度摘要
| 维度 | 测试数量 | 触发数量 | 平均收益率 | 中位收益率 | 最差收益率 | 最好收益率 | 最佳 case |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| spent_x_tax | 1750 | 187 | 44.5701 | 38.0501 | 33.7736 | 104.4073 | spent=10000|tax=94 |
| spent_x_discount | 910 | 82 | 39.5994 | 40.0431 | 33.7736 | 40.5818 | spent=10000|discount=0.98 |
| tax_x_discount | 1300 | 52 | 39.5308 | 40.0431 | 33.7736 | 40.5818 | tax=99|discount=0.98 |

## 候选策略场景压力测试
| 候选 | 真实 SR | 场景数 | 触发场景 | 中位收益率 | 最差收益率 | 最坏场景 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| baseline_100k_tax92 | 2 buys, spent 100V, pnl 38.050128V/38.0501%, first tax 92, spent 132032.472, entry 359.711454, cost 364.638858 | 23 | 18 | 35.5602 | 16.1698 | board_cost_over_20pct |
| conservative_100k_tax90 | 1 buys, spent 50V, pnl 20.021538V/40.0431%, first tax 90, spent 164791.135, entry 362.478804, cost 380.642784 | 23 | 17 | 35.9642 | 7.2631 | combined_slow_bad |
| strict_100k_tax92_discount98 | 1 buys, spent 50V, pnl 20.021538V/40.0431%, first tax 90, spent 164791.135, entry 362.478804, cost 380.642784 | 23 | 18 | 37.1671 | 16.7819 | board_cost_over_20pct |
| aggressive_50k_tax98_discount98 | 1 buys, spent 50V, pnl 41.912947V/83.8259%, first tax 93, spent 54966.025, entry 276.145245, cost 331.375072 | 23 | 19 | 71.698 | 14.4014 | combined_slow_bad |
| aggressive_50k_tax98_discount100 | 2 buys, spent 100V, pnl 59.467125V/59.4671%, first tax 93, spent 54966.025, entry 276.145245, cost 331.375072 | 23 | 19 | 53.3389 | 22.1447 | board_cost_over_20pct |
| capital_cap_100k_tax92_max100 | 2 buys, spent 100V, pnl 38.050128V/38.0501%, first tax 92, spent 132032.472, entry 359.711454, cost 364.638858 | 23 | 18 | 37.3606 | 20.6164 | combined_slow_bad |
| no_burst_100k_tax92 | 3 buys, spent 150V, pnl 57.92699V/38.618%, first tax 92, spent 132032.472, entry 359.711454, cost 364.638858 | 23 | 18 | 34.5088 | 11.1428 | combined_slow_bad |

## 蒙特卡洛扰动
| 候选 | 运行次数 | 触发次数 | P5 | 中位 | P95 | 最差 | 最好 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline_100k_tax92 | 500 | 297 | 1.495 | 16.7433 | 33.1167 | -3.1446 | 41.1193 |
| strict_100k_tax92_discount98 | 500 | 264 | 2.4348 | 16.3843 | 35.6525 | -1.6243 | 41.0485 |
| aggressive_50k_tax98_discount98 | 500 | 369 | 6.087 | 22.0814 | 70.5898 | 1.9054 | 93.1123 |

## 合成数据形态测试
| 形态 | 候选数 | 触发数 | 中位收益率 | 最差收益率 | 最好收益率 | 最佳候选 | 最坏候选 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| actual | 7 | 7 | 40.0431 | 38.0501 | 83.8259 | aggressive_50k_tax98_discount98 | baseline_100k_tax92 |
| price_up_50pct | 7 | 6 | 100.8946 | 100.8946 | 167.1663 | aggressive_50k_tax98_discount98 | baseline_100k_tax92 |
| price_down_30pct | 7 | 7 | -6.953 | -9.9179 | -1.1044 | capital_cap_100k_tax92_max100 | conservative_100k_tax90 |
| late_dump_50pct | 7 | 7 | -30.9749 | -35.6789 | -28.5143 | conservative_100k_tax90 | no_burst_100k_tax92 |
| early_pump_then_flat | 7 | 2 | 62.916 | 62.916 | 62.916 | aggressive_50k_tax98_discount98 | aggressive_50k_tax98_discount98 |
| team_low_cost_included | 7 | 0 | 0 | 0 | 0 | - | - |
| board_cost_overstated | 7 | 7 | 20.4503 | 11.1551 | 38.0501 | capital_cap_100k_tax92_max100 | conservative_100k_tax90 |
| whale_slow_accumulation | 7 | 2 | 41.0767 | 40.0431 | 42.1103 | aggressive_50k_tax98_discount100 | aggressive_50k_tax98_discount98 |
| whale_fast_accumulation | 7 | 7 | 40.0431 | 38.0501 | 94.298 | aggressive_50k_tax98_discount98 | baseline_100k_tax92 |

## 当前解释
- 上一次结论只能证明历史 SR 上几个点位有效，不能证明策略稳健。
- 这次测试覆盖单参数梯度、二维组合梯度、采样/延迟/滑点/榜单偏差/税率偏差和组合坏情况。
- 自动买入仍不应直接上线；下一步应先做实时 dry-run 信号记录，并用真实新项目验证。

