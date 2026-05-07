# Virtuals Whale Radar Plan 纲领

> Owner: Codex.
> Update rule: 每次完成代码、脚本、测试能力或部署流程变更后，更新本文件和对应阶段子 plan。

## 1. 文档分层

- 需求纲领：`docs/requirements-outline.md`，只由用户更新。
- Plan 纲领：本文件，只保留阶段索引、当前状态和关键链接。
- Todo 纲领：`docs/todo-index.md`，只保留阶段执行索引和完成状态。
- 阶段子 plan：`docs/phases/phase-XXX-*-plan.md`，记录详细方案、边界、验收口径。
- 阶段子 todo：`docs/phases/phase-XXX-*-todo.md`，记录详细执行清单。
- 历史长文档：`docs/PLAN.md` 继续保留完整历史与验收事实。

## 2. 当前阶段索引

| Phase | 状态 | 子 plan | 子 todo | 说明 |
| --- | --- | --- | --- | --- |
| 051 | Done | `docs/launch-strategy-backtest-2026-05-07.md` | `docs/todo.md#phase-5198-分钟税率项目自动买入策略离线回测` | 98 分钟税率项目策略离线回测、压力测试、消融测试已完成第一轮。 |
| 052 | Validated | `docs/phases/phase-052-strategy-test-matrix-plan.md` | `docs/phases/phase-052-strategy-test-matrix-todo.md` | 统一 runner 已完成并用 SR/ISC/TDS Chainstack replay 生成矩阵报告。 |
| 053 | In Progress | `docs/phases/phase-053-strategy-lab-ui-plan.md` | `docs/phases/phase-053-strategy-lab-ui-todo.md` | 将策略测试矩阵结果接入管理后台 Strategy Lab 只读页面。 |

## 3. 更新规则

- 新阶段必须先创建子 plan 和子 todo，再改代码。
- `docs/PLAN.md` 只追加阶段摘要，不再承载所有细节。
- 本文件只写索引和状态，不写完整执行过程。
- 阶段完成时，将状态改为 `Done`，并在对应子 plan 记录验收结果链接。
