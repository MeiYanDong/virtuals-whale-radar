# SR_EVENT_REPLAY Event-Level Replay Strategy Report

本报告从链上重新拉取项目发射窗口，按 `pool_state_change + tax_tick + heartbeat` 构造本地离线时间线。
它只写入隔离 replay DB，不触碰生产库，不发送交易。

## 口径
- 项目：`SR_EVENT_REPLAY` / Virtuals ID `70972`。
- RPC：报告只记录 provider 角色，不记录 endpoint token。
- history/log/market RPC：`chainstack`。
- receipt RPC：`chainstack`。
- `pool_state_change` 覆盖 buy、sell、unknown pool event。
- `tax_tick` 是税率变化瞬间；即使没有交易也单独采样。
- 收益只看 tax 降到 `1%` 时的 end 表现，不输出默认 `1m / 3m / 5m / 10m`。

## 数据规模
| tx | pool events | buy | sell | unknown | tax ticks | samples | parsed buys | inserted buys |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 751 | 751 | 601 | 24 | 126 | 99 | 1089 | 601 | 601 |

## 候选规则
| Rule | 买入 | 投入 | end收益 | End PnL | 首买 |
| --- | ---: | ---: | ---: | ---: | --- |
| gate_5k_tax95_fdv_one_per_tax | 6 | 300 | 62.9736% | 188.920764 | tax 95, board 13834.996V, FDV 297.593225万, cost 440.588794万, costPos 1/19, triggers buy |
| gate_5k_tax94_fdv_one_per_tax | 6 | 300 | 58.5259% | 175.57776 | tax 94, board 15214.212V, FDV 249.188523万, cost 433.446604万, costPos 1/19, triggers heartbeat,tax_tick |
| gate_5k_tax93_fdv_one_per_tax | 5 | 250 | 52.3308% | 130.826949 | tax 93, board 21210.792V, FDV 219.402531万, cost 385.854617万, costPos 1/19, triggers heartbeat,tax_tick |
| gate_5k_tax92_fdv_one_per_tax | 4 | 200 | 36.6064% | 73.21281 | tax 92, board 127032.472V, FDV 331.287606万, cost 340.665488万, costPos 8/19, triggers buy,heartbeat,tax_tick |
| gate_5k_tax90_fdv_one_per_tax | 2 | 100 | 35.2882% | 35.288247 | tax 90, board 164791.135V, FDV 340.743583万, cost 358.868715万, costPos 6/19, triggers heartbeat,tax_tick |
| gate_5k_tax91_fdv_one_per_tax | 3 | 150 | 34.6286% | 51.94297 | tax 91, board 159224.769V, FDV 354.225678万, cost 356.238692万, costPos 8/19, triggers heartbeat,tax_tick |
| gate_5k_tax89_fdv_one_per_tax | 1 | 50 | 31.9924% | 15.996217 | tax 89, board 179856.135V, FDV 357.760121万, cost 361.971254万, costPos 7/19, triggers heartbeat,tax_tick |

## 最佳规则验证

- Rule：`gate_5k_tax95_fdv_one_per_tax`。
- 样本数：`1089`。
- 满足硬条件的信号样本：`54`。
- 信号簇数量：`1`。
- 执行后买入次数：`6`。
- 执行层拦截：`{'missing_board_cost': 11, 'spent_threshold': 23, 'tax_threshold': 9, 'min_whale_rows': 12, 'same_tax_period': 46, 'fdv_not_below_cost': 979, 'max_project_spend': 2, 'not_live': 1}`。
- 逻辑说明：样本数增加不等于买入机会增加；买入由硬条件、每个税率档位最多买一次、项目最大投入共同决定。

### 信号簇
| 簇 | 行数 | 开始 | 结束 | 开始条件 | 结束条件 |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 54 | 1776049497 | 1776049815 | tax 95, board 13834.996V, FDV 297.593225万, cost 440.588794万 | tax 89, board 179856.135V, FDV 357.760121万, cost 361.971254万 |

### 执行限制对照
| 模式 | 买入 | 投入 | end收益 |
| --- | ---: | ---: | ---: |
| current | 6 | 300 | 62.9736% |
| noTaxPeriodLimitMaxSpend | 6 | 300 | 68.6025% |
| legacy60sCooldownNoBurst | 6 | 300 | 48.4738% |
| legacy30sCooldownNoBurst | 6 | 300 | 66.7809% |

## 执行信息
- 区块窗口：`44629933 -> 44632873`
- 时间窗口：`1776049213 -> 1776055093`
- sample JSONL：`data/replay-event-level/sr_event_replay-20260510T073102Z-samples.jsonl`
- isolated DB：`data/replay-event-level/sr_event_replay-20260510T073102Z.db`
- historical eth_call：`True`
