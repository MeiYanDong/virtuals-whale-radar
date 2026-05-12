# Phase 053 - Virtuals Buy Route Universality Audit

## 结论

- 对普通用户的 Virtuals direct buy，本地样本支持同一套入口：router `0x1a540088125d00dd3990f9da45ca0859af4d3b01`，selector `0x706910ff`。
- 这不是所有交易的通用入口：TDS 团队/初始化交易出现同 router 但 selector `0x214013ca`；SR 有 1 个 alternate/aggregator route。
- 因此执行层应该把 `direct_buy` 当作第一版自动买入支持范围，把 team/initialization 和 aggregator route 排除在自动买入外。
- 判断口径：交易必须同时满足 `to == direct router`、`selector == 0x706910ff`、`value == 0`，并通过 TxSimulator 的 balance/allowance/eth_call/gas 检查。
- 对大户榜单过滤也有价值：`team_or_initialization_route` 可以作为团队购买的高置信自动过滤信号；最小判断只保留 direct router + `selector == 0x214013ca`。
- 本阶段仍然不签名、不广播。

## 项目摘要

| Project | Samples | Direct Buy | Route Classes | Selectors |
| --- | ---: | ---: | --- | --- |
| SR_EVENT_REPLAY | 80 | 77 | `{"team_or_initialization_route": 1, "direct_buy": 77, "alternate_or_aggregator_route": 2}` | `{"0x214013ca": 1, "0x706910ff": 77, "0x1fad948c": 2}` |
| ISC_EVENT_REPLAY | 80 | 79 | `{"team_or_initialization_route": 1, "direct_buy": 79}` | `{"0x214013ca": 1, "0x706910ff": 79}` |
| TDS | 80 | 76 | `{"team_or_initialization_route": 1, "direct_buy": 76, "alternate_or_aggregator_route": 3}` | `{"0x214013ca": 1, "0x706910ff": 76, "0x1fad948c": 3}` |

## 非 Direct Buy 样本

| Project | Route Class | Tx | Router | Selector | Buyer |
| --- | --- | --- | --- | --- | --- |
| SR_EVENT_REPLAY | team_or_initialization_route | `0x1b74a3c0...dd5b1301` | `0x1a540088...af4d3b01` | `0x214013ca` | `0x81f7ca6a...07491415` |
| SR_EVENT_REPLAY | alternate_or_aggregator_route | `0x6ee6f62d...72434d53` | `0x5ff137d4...026d2789` | `0x1fad948c` | `0x720ca2ce...727e025e` |
| SR_EVENT_REPLAY | alternate_or_aggregator_route | `0x4aaa9695...9e76565e` | `0x5ff137d4...026d2789` | `0x1fad948c` | `0x3b38d5d0...31a80b4a` |
| ISC_EVENT_REPLAY | team_or_initialization_route | `0x756a8478...ff3203b3` | `0x1a540088...af4d3b01` | `0x214013ca` | `0x81f7ca6a...07491415` |
| TDS | team_or_initialization_route | `0xf187f6b1...5caa0ccf` | `0x1a540088...af4d3b01` | `0x214013ca` | `0x81f7ca6a...07491415` |
| TDS | alternate_or_aggregator_route | `0x2a0e978a...10695aff` | `0x5ff137d4...026d2789` | `0x1fad948c` | `0x3b38d5d0...31a80b4a` |
| TDS | alternate_or_aggregator_route | `0xebbcbebf...02b6d321` | `0x5ff137d4...026d2789` | `0x1fad948c` | `0x3b38d5d0...31a80b4a` |
| TDS | alternate_or_aggregator_route | `0x4976132a...e7feeadf` | `0x5ff137d4...026d2789` | `0x1fad948c` | `0x3b38d5d0...31a80b4a` |
