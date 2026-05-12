# ISC_EVENT_REPLAY Event-Level Replay Strategy Report

本报告从链上重新拉取项目发射窗口，按 `pool_state_change + tax_tick + heartbeat` 构造本地离线时间线。
它只写入隔离 replay DB，不触碰生产库，不发送交易。

## 口径
- 项目：`ISC_EVENT_REPLAY` / Virtuals ID `72752`。
- RPC：报告只记录 provider 角色，不记录 endpoint token。
- history/log/market RPC：`chainstack`。
- receipt RPC：`chainstack`。
- `pool_state_change` 覆盖 buy、sell、unknown pool event。
- `tax_tick` 是税率变化瞬间；即使没有交易也单独采样。
- 收益只看 tax 降到 `1%` 时的 end 表现，不输出默认 `1m / 3m / 5m / 10m`。

## 数据规模
| tx | pool events | buy | sell | unknown | tax ticks | samples | parsed buys | inserted buys |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 600 | 600 | 322 | 41 | 237 | 99 | 1576 | 322 | 322 |

## 候选规则
| Rule | 买入 | 投入 | end收益 | End PnL | 首买 |
| --- | ---: | ---: | ---: | ---: | --- |
| gate_5k_tax89_fdv_one_per_tax | 6 | 300 | 38.1828% | 114.548261 | tax 89, board 43919.553V, FDV 155.442918万, cost 192.632804万, costPos 1/19, triggers heartbeat,tax_tick |
| gate_5k_tax90_fdv_one_per_tax | 6 | 300 | 35.8907% | 107.672137 | tax 90, board 32421.854V, FDV 150.885475万, cost 200.848931万, costPos 1/19, triggers heartbeat,tax_tick |
| gate_5k_tax91_fdv_one_per_tax | 6 | 300 | 32.5695% | 97.708544 | tax 91, board 23478.198V, FDV 156.097062万, cost 209.809943万, costPos 1/19, triggers heartbeat,tax_tick |
| gate_5k_tax92_fdv_one_per_tax | 6 | 300 | 29.4133% | 88.239854 | tax 92, board 14839.657V, FDV 159.153397万, cost 226.384906万, costPos 1/19, triggers heartbeat,tax_tick |
| gate_5k_tax95_fdv_one_per_tax | 6 | 300 | 24.3695% | 73.108392 | tax 93, board 14839.657V, FDV 181.889597万, cost 226.384906万, costPos 1/19, triggers buy |
| gate_5k_tax94_fdv_one_per_tax | 6 | 300 | 24.3695% | 73.108392 | tax 93, board 14839.657V, FDV 181.889597万, cost 226.384906万, costPos 1/19, triggers buy |
| gate_5k_tax93_fdv_one_per_tax | 6 | 300 | 24.3695% | 73.108392 | tax 93, board 14839.657V, FDV 181.889597万, cost 226.384906万, costPos 1/19, triggers buy |

## 最佳规则验证

- Rule：`gate_5k_tax89_fdv_one_per_tax`。
- 样本数：`1576`。
- 满足硬条件的信号样本：`488`。
- 信号簇数量：`2`。
- 执行后买入次数：`6`。
- 执行层拦截：`{'missing_board_cost': 45, 'spent_threshold': 22, 'tax_threshold': 105, 'same_tax_period': 122, 'max_project_spend': 360, 'fdv_not_below_cost': 915, 'not_live': 1}`。
- 逻辑说明：样本数增加不等于买入机会增加；买入由硬条件、每个税率档位最多买一次、项目最大投入共同决定。

### 信号簇
| 簇 | 行数 | 开始 | 结束 | 开始条件 | 结束条件 |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 433 | 1777473604 | 1777474997 | tax 89, board 43919.553V, FDV 155.442918万, cost 192.632804万 | tax 66, board 78999.387V, FDV 162.002883万, cost 164.22798万 |
| 2 | 55 | 1777475524 | 1777475754 | tax 57, board 81501.083V, FDV 163.011163万, cost 164.567075万 | tax 54, board 81904.165V, FDV 164.495815万, cost 164.567094万 |

### 执行限制对照
| 模式 | 买入 | 投入 | end收益 |
| --- | ---: | ---: | ---: |
| current | 6 | 300 | 38.1828% |
| noTaxPeriodLimitMaxSpend | 6 | 300 | 25.5555% |
| legacy60sCooldownNoBurst | 6 | 300 | 38.1828% |
| legacy30sCooldownNoBurst | 6 | 300 | 30.288% |

## 执行信息
- 区块窗口：`45341829 -> 45344768`
- 时间窗口：`1777473004 -> 1777478884`
- sample JSONL：`data/replay-event-level/isc_event_replay-20260510T085419Z-samples.jsonl`
- isolated DB：`data/replay-event-level/isc_event_replay-20260510T085419Z.db`
- historical eth_call：`True`
