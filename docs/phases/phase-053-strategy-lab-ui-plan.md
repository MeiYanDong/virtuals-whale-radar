# Phase 053 Strategy Lab UI Plan

## 1. 目标

把 Phase 052 的策略测试矩阵结果接入管理后台，形成只读 Strategy Lab 页面。该页面只展示离线 replay 报告，不触发重跑、不写数据库、不发送交易。

## 2. 非目标

- 不接热钱包。
- 不发真实交易。
- 不在前端直接读取本地文件。
- 不把完整 `results` 明细一次性返回给浏览器。
- 不做 realtime dry-run signal emitter；该能力作为下一阶段。

## 3. 后端设计

- 新增管理员只读接口：`/api/admin/strategy-lab/report`。
- 数据来源：`data/backtests/strategy-test-matrix-20260507.json`，不存在时选择最新 `strategy-test-matrix-*.json`。
- 返回摘要字段：
  - datasets。
  - rule / scenario / result counts。
  - suite summary。
  - dry-run candidates。
  - reject list。
  - stable zone。
  - top by risk-adjusted score。
  - variable contribution。
  - failure cases。
  - overfit warnings。
- 不返回完整 `results` 数组，避免浏览器加载 `13MB+` 原始 JSON。

## 4. 前端设计

- 新增管理员页面：`/admin/strategy-lab`。
- 侧边栏新增 `Strategy Lab` 入口。
- 页面结构：
  - 总览 KPI。
  - replay 数据集。
  - dry-run candidates。
  - risk-adjusted top。
  - stable zone。
  - variable contribution。
  - suite summary。
  - reject list。
  - failure cases。
  - overfit warnings。

## 5. 验收标准

- 管理员登录后能通过侧边栏进入 Strategy Lab。
- 页面能展示 Phase 052 最新报告摘要。
- 页面不会影响 writer / realtime / backfill。
- `npm run build` 通过。
- 生产同步后 `/api/admin/strategy-lab/report` 可访问，后台前端加载最新构建。
