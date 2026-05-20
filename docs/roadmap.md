# Roadmap

## Base 生态生产提交

状态：暂停。

这是远期上架/比赛提交阶段，不属于当前主线。当前产品优先级已经从外部分发切回自用实盘盈利闭环；Base Account / OKX Wallet / Base USDC Billing 保留为已完成基础能力，但短期不继续投入 Base 生态上架、比赛提交和面向外部用户的体验打磨。

提交给 Base 生态、Base App 或 Base 相关比赛时，提交对象必须是生产版本，而不是本地测试版本。

硬性边界：

- 对外 Demo URL 必须来自 `https://virtuals.club`。
- 截图、录屏、产品说明和评审入口必须基于生产站真实页面。
- `localhost`、本地 Vite dev、本地测试用户、本地 smoke 数据、本地 `0.01 USDC` 测试套餐只能作为内部验收证据，不进入 Base 提交包。
- 生产提交前必须确认 `BILLING_TEST_PLAN_ENABLED=false`，避免对外展示测试套餐。
- 生产提交前必须记录部署 commit、生产健康检查结果、生产 `/base`、生产 `/auth/login` 和生产 `/app/billing` 的验收结果。

恢复该方向时的执行顺序：

1. 确认当前主线已经证明自用实盘盈利能力。
2. 确认生产站仍可通过 `https://virtuals.club/base`、`/auth/login`、`/app/projects`、`/app/billing` 完成基础验收。
3. 确认 `BILLING_TEST_PLAN_ENABLED=false`。
4. 用生产站截图和生产 Demo URL 更新 `docs/base-ecosystem-listing.md`。
5. 再提交给 Base 生态或比赛评审。
