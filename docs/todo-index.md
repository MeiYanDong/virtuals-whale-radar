# Virtuals Whale Radar Todo 纲领

> Owner: Codex.
> Update rule: 每次完成代码、脚本、测试能力或部署流程变更后，更新本文件和对应阶段子 todo。

## 1. 当前执行索引

| Phase | 状态 | 子 todo | 下一步 |
| --- | --- | --- | --- |
| 051 | Done | `docs/todo.md#phase-5198-分钟税率项目自动买入策略离线回测` | 保留历史记录，不再继续追加细节。 |
| 052 | Validated | `docs/phases/phase-052-strategy-test-matrix-todo.md` | 买入策略已冻结为 after1 横盘暂停版；双策略自动卖出已完成本地回测，生产卖出执行接入进入 Phase 053。 |
| 053 | In Progress | `docs/phases/phase-053-launch-execution-pipeline-todo.md` | ROO live 买卖、回归归档和通用启动编排已完成；下一步是新 live 项目用 `schedule_launch_services.py` 拉起服务并验证全量 samples/归档。 |
| 054 | Production Verified | `docs/phases/phase-054-team-address-filter-todo.md` | selector 高置信过滤已接入并完成 SR/ISC/TDS 只读验证；overview API 与生产项目详情页 UI 烟测均已通过。 |
| 055 | Production Probed | `docs/phases/phase-055-runtime-strategy-control-todo.md` | 生产网页保存、DB 同步和执行器热读取探针已通过；下一步随本轮 commit/push 固化。 |
| 056 | Local Verified | `docs/phases/phase-056-runtime-autosell-control-todo.md` | 自动卖出控制台、后端配置 API、执行器热加载和本地热加载探针已完成；尚未同步生产。 |

## 2. 执行规则

- 每个阶段的详细 checkbox 只写在阶段子 todo。
- 本文件只维护阶段级状态，不复制阶段细节。
- 代码变更完成后，必须同步更新对应子 todo。
- 若阶段产生新的测试报告或运行结果，在子 todo 中记录路径，在本文件只更新状态。
