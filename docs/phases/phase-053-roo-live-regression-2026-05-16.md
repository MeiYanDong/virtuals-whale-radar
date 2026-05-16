# Phase 053 ROO Live Regression 2026-05-16

## 1. 目标

用 ROO 真实 live 日志做内盘回归测试，验证自动买入、自动卖出、执行账本、归档和回测复用链路。测试不发送新交易，不修改生产业务数据。

## 2. 数据源

- 标准归档：`/opt/virtuals-whale-radar/data/launch-archives/ROO-live-regression-20260516`
- 买入单一样本源归档：`/opt/virtuals-whale-radar/data/launch-archives/ROO-autobuy-canonical-20260516`
- 卖出单一样本源归档：`/opt/virtuals-whale-radar/data/launch-archives/ROO-autosell-canonical-20260516`
- 买入日志：`/opt/virtuals-whale-radar/data/execution/launch-autobuy-ROO.jsonl`
- 卖出日志：`/opt/virtuals-whale-radar/data/execution/launch-autosell-ROO.jsonl`
- dry-run 日志：`/opt/virtuals-whale-radar/data/execution/live-strategy-dry-run-ROO.jsonl`
- 执行账本：`launch_execution_ledger`

## 3. 归档结果

标准归档输出：

- `sampleCount=7993`
- `eventCount=505`
- `ledgerCount=240`
- `fuseCount=1`
- `warnings=[]`
- `productionDbTouched=false`
- `tradeSent=false`

单一样本源输出：

- autobuy canonical：`4283` samples
- autosell canonical：`1421` samples

## 4. 买入策略回放

当前主策略：`gate_5k_tax95_fdv_one_per_tax` + `dynamic_25v_dip20_after1_flat10_no_cap`

- 买入次数：`6`
- 总投入：`150 VIRTUAL`
- 我方加权成本：`482.735918 万 USD`
- 最终价值：`197.826781 VIRTUAL`
- 最终收益：`+47.826781 VIRTUAL`
- 最终收益率：`+31.8845%`

首笔买入：

- 税率：`95`
- 买入：`25 VIRTUAL`
- 含税估算 FDV：`523.896018 万 USD`
- 榜单 V：`7778.551`
- 成本位：`1/19`

最后一笔买入：

- 税率：`9`
- 买入：`25 VIRTUAL`
- 含税估算 FDV：`549.279206 万 USD`
- 榜单 V：`244769.94`
- 成本位：`6/19`

## 5. 卖出策略回放

当前主策略：`dual_roi_large_buy_sell`

- 卖出次数：`1`
- 触发条件：税率 `<=30%`，单笔买入 `>=5000 VIRTUAL`，自身收益率 `>=30%`
- 卖出仓位：原始总仓位 `30%`
- 卖出后最终收益率：`+32.7369%`
- 纯持有收益率：`+31.8909%`
- 相对纯持有提升：`+0.846%`

结论：ROO 上卖出策略未出现误杀，且略优于纯持有。

## 6. 链上 receipt 复核

重新通过 execution RPC 查询 ROO live 期间 4 笔真实交易 receipt：

| 类型 | tx | status | block | gasUsed |
| --- | --- | --- | --- | --- |
| buy | `0xa1a2786e18e1b83f66724d4b930bd42ad73883df3f5f86c3bc21bd8ef0afd950` | `0x1` | `45905833` | `287749` |
| buy | `0xcf25aede650a00f134355ba73e8407fced8ccbd7c634c093919a09f95c4806d5` | `0x1` | `45907033` | `270649` |
| sell | `0x87ccc9c6935362af1786eeab5974c52cafc938c404a0b275de7be2b117a7398b` | `0x1` | `45906445` | `202634` |
| sell | `0xf476b21b47df21a012f47c62a2c90057a1d03795dedb50272b0107e9b291e7ff` | `0x1` | `45907039` | `202634` |

## 7. 结论

- ROO 真实日志可以作为后续内盘回归测试基准。
- 标准归档链路能把生产数据冻结为回测档案。
- 当前买入策略在 ROO 回放中为正收益。
- 当前双条件卖出策略在 ROO 回放中没有误杀，略优于纯持有。
- ROO 当前项目状态已经 `ended`，不能再用于真实内盘买入；后续只能在新 live 项目窗口验证新的广播。
