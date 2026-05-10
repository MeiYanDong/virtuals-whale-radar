# Phase 052 Strategy Test Matrix Todo

## 1. 文档冻结

- [x] 创建阶段子 plan：`docs/phases/phase-052-strategy-test-matrix-plan.md`。
- [x] 创建阶段子 todo：`docs/phases/phase-052-strategy-test-matrix-todo.md`。
- [x] 用户确认 Phase 052 的默认测试目标和风险边界。

## 2. 数据输入盘点

- [x] 列出本地和服务器已有 replay samples。
- [x] 确认 SR 高采样样本字段完整性。
- [x] 确认 ISC/TDS 对照样本字段完整性。
- [x] 定义后续真实项目 dry-run 日志格式。

## 3. 控制变量矩阵

- [x] 实现大户榜单 V 梯度。
- [x] 实现税率梯度。
- [x] 实现 FDV 成本折扣梯度。
- [x] 实现冷却时间梯度。
- [x] 实现连续买入限制梯度。
- [x] 实现最大项目投入梯度。
- [x] 实现最小榜单人数梯度。

## 4. 取消变量矩阵

- [x] 实现只看税率。
- [x] 实现只看榜单 V。
- [x] 实现只看 FDV 成本。
- [x] 实现榜单 V + 税率。
- [x] 实现榜单 V + FDV。
- [x] 实现税率 + FDV。
- [x] 实现榜单 V + 税率 + FDV。
- [x] 实现取消冷却。
- [x] 实现取消最大投入。
- [x] 实现取消最小榜单人数。

## 5. 多变量组合矩阵

- [x] 实现 `spent x tax`。
- [x] 实现 `spent x fdv_discount`。
- [x] 实现 `tax x fdv_discount`。
- [x] 实现 `spent x tax x fdv_discount`。
- [x] 实现 `cooldown x max_project_spend`。
- [x] 实现 `min_rows x spent`。
- [x] 实现 `burst_limit x cooldown`。

## 6. 场景模拟

- [x] 实现价格路径模拟。
- [x] 实现大户行为模拟。
- [x] 实现团队地址污染模拟。
- [x] 实现税率异常模拟。
- [x] 实现 RPC / 数据延迟模拟。
- [x] 实现执行层滑点和确认延迟模拟。

## 7. 统一报告

- [x] 输出 JSON 报告：`data/backtests/strategy-test-matrix-20260507.json`。
- [x] 输出 Markdown 报告：`docs/phases/phase-052-strategy-test-matrix-report.md`。
- [x] 输出 Top by final return。
- [x] 输出 Top by risk-adjusted score。
- [x] 输出 Stable zone。
- [x] 输出 Failure cases。
- [x] 输出 Variable contribution。
- [x] 输出 Overfit warning。
- [x] 输出 Dry-run candidates。
- [x] 输出 Reject list。
- [x] 追加硬门槛重筛：榜单人数 `20`、榜单 V `>= 50,000`、税率 `<= 95%`。

## 8. 验证

- [x] 用 SR 高采样样本跑完整矩阵。
- [x] 用 ISC 样本跑对照矩阵。
- [x] 用 TDS 样本跑对照矩阵。
- [x] 确认脚本只读 replay，不写生产 DB。
- [x] 确认报告不包含 RPC key、钱包私钥或 endpoint token。

## 9. 文档同步

- [x] 更新 `docs/plan-index.md`。
- [x] 更新 `docs/todo-index.md`。
- [x] 更新 `docs/PLAN.md` 阶段摘要。
- [x] 更新 `docs/todo.md` 阶段摘要。
- [x] 如需生产同步，更新 `scripts/ops/deploy_production_safe.sh` 白名单。
