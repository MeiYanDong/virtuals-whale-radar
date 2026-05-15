# Virtuals Whale Radar Todo 纲领

> Owner: Codex.
> Update rule: 每次完成代码、脚本、测试能力或部署流程变更后，更新本文件和对应阶段子 todo。

## 1. 当前执行索引

| Phase | 状态 | 子 todo | 下一步 |
| --- | --- | --- | --- |
| 051 | Done | `docs/todo.md#phase-5198-分钟税率项目自动买入策略离线回测` | 保留历史记录，不再继续追加细节。 |
| 052 | Validated | `docs/phases/phase-052-strategy-test-matrix-todo.md` | 买入策略已冻结为 after1 横盘暂停版；双策略自动卖出已完成本地回测，生产卖出执行接入进入 Phase 053。 |
| 053 | In Progress | `docs/phases/phase-053-launch-execution-pipeline-todo.md` | execution RPC 已收口到独立 Chainstack endpoint，live 发射档案归档已接入，生产健康已复核；下一步是真实 live 窗口端到端验证、归档落地、热路径缓存和 RPC 压力观察。 |
| 054 | Prod Deployed / UI Verify Pending | `docs/phases/phase-054-team-address-filter-todo.md` | selector 高置信过滤已接入并完成 SR/ISC/TDS 只读验证；overview API 生产烟测已通过，下一步复测生产项目详情页 UI。 |

## 2. 执行规则

- 每个阶段的详细 checkbox 只写在阶段子 todo。
- 本文件只维护阶段级状态，不复制阶段细节。
- 代码变更完成后，必须同步更新对应子 todo。
- 若阶段产生新的测试报告或运行结果，在子 todo 中记录路径，在本文件只更新状态。
