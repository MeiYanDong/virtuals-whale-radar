# Virtuals Whale Radar Todo 纲领

> Owner: Codex.
> Update rule: 每次完成代码、脚本、测试能力或部署流程变更后，更新本文件和对应阶段子 todo。

## 1. 当前执行索引

| Phase | 状态 | 子 todo | 下一步 |
| --- | --- | --- | --- |
| 051 | Done | `docs/todo.md#phase-5198-分钟税率项目自动买入策略离线回测` | 保留历史记录，不再继续追加细节。 |
| 052 | Validated | `docs/phases/phase-052-strategy-test-matrix-todo.md` | 买入策略已冻结为 after1 横盘暂停版；双策略自动卖出已完成本地回测，生产卖出执行接入进入 Phase 053。 |
| 053 | In Progress | `docs/phases/phase-053-launch-execution-pipeline-todo.md` | execution RPC 已收口到独立 Chainstack endpoint；下一步是真实 live 窗口端到端验证、热路径缓存和 RPC 压力观察。 |
| 054 | Local Validated | `docs/phases/phase-054-team-address-filter-todo.md` | 同步前做完整 diff 审核；如上线，走生产安全同步并复测 overview。 |

## 2. 执行规则

- 每个阶段的详细 checkbox 只写在阶段子 todo。
- 本文件只维护阶段级状态，不复制阶段细节。
- 代码变更完成后，必须同步更新对应子 todo。
- 若阶段产生新的测试报告或运行结果，在子 todo 中记录路径，在本文件只更新状态。
