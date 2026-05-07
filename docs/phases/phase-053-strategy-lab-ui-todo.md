# Phase 053 Strategy Lab UI Todo

## 1. 后端 API

- [x] 新增 `latest_strategy_test_report_path()`。
- [x] 新增 `build_strategy_lab_report_payload()`。
- [x] 新增 `/api/admin/strategy-lab/report`。
- [x] API 只返回摘要，不返回完整 `results`。
- [x] API 仅管理员可访问。

## 2. 前端接入

- [x] 新增 `StrategyLabReportResponse` 等类型。
- [x] 新增 `queryKeys.strategyLabReport`。
- [x] 新增 `dashboardApi.admin.getStrategyLabReport()`。
- [x] 新增 `/admin/strategy-lab` 路由。
- [x] 侧边栏新增 `Strategy Lab`。

## 3. 页面实现

- [x] 展示总览 KPI。
- [x] 展示 replay 数据集。
- [x] 展示 Dry-run Candidates。
- [x] 展示 Top By Risk Adjusted Score。
- [x] 展示 Stable Zone。
- [x] 展示 Variable Contribution。
- [x] 展示 Suite Summary。
- [x] 展示 Reject List。
- [x] 展示 Failure Cases。
- [x] 展示 Overfit Warnings。

## 4. 验证

- [x] `python3 -m py_compile virtuals_bot.py`。
- [x] `npm run build`。
- [x] 修复 Chainstack 单段路径 endpoint 在 `/health` 中未打码的问题。
- [x] 生产同步后验证 `/api/admin/strategy-lab/report` 路由权限边界。
- [x] 生产同步后验证 `/admin/strategy-lab` 页面加载。

## 5. 文档同步

- [x] 更新 `docs/plan-index.md`。
- [x] 更新 `docs/todo-index.md`。
- [x] 更新 `docs/PLAN.md`。
- [x] 更新 `docs/todo.md`。
- [x] 更新 `scripts/ops/deploy_production_safe.sh` 白名单。
