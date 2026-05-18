# Roadmap

## Base 生态生产提交

这是远期上架/比赛提交阶段，不属于当前 Base 入口改造的执行计划。

提交给 Base 生态、Base App 或 Base 相关比赛时，提交对象必须是生产版本，而不是本地测试版本。

硬性边界：

- 对外 Demo URL 必须来自 `https://virtuals.club`。
- 截图、录屏、产品说明和评审入口必须基于生产站真实页面。
- `localhost`、本地 Vite dev、本地测试用户、本地 smoke 数据、本地 `0.01 USDC` 测试套餐只能作为内部验收证据，不进入 Base 提交包。
- 生产提交前必须确认 `BILLING_TEST_PLAN_ENABLED=false`，避免对外展示测试套餐。
- 生产提交前必须记录部署 commit、生产健康检查结果、生产 `/base`、生产 `/auth/login` 和生产 `/app/billing` 的验收结果。

后续执行顺序：

1. 用当前分支完成代码审计，确认 Base 入口改动没有误动自动买入、自动卖出、execution RPC、fuse 和 scheduler。
2. 使用生产安全同步流程部署到 `https://virtuals.club`。
3. 在生产站验收 `/base`、`/auth/login`、`/app/projects`、`/app/billing`。
4. 用生产站截图和生产 Demo URL 更新 `docs/base-ecosystem-listing.md`。
5. 再提交给 Base 生态或比赛评审。
