# Base 生态上架资料包

## 产品定位

Virtuals Whale Radar 是面向 Virtuals 新项目发射窗口的实时观察台，核心能力是把链上买入、税率变化、大户榜单、钱包持仓和延迟状态整理成可操作的项目看板。

Base 在本产品中的角色是分发与支付入口：用户可以通过 Base Account 或 OKX Wallet 进入，也可以用 Base USDC 购买积分解锁项目。产品定位仍然是 Virtuals 项目雷达，不改成泛 Base 项目雷达。

## 一句话介绍

Track Virtuals launches on Base with live whale boards, tax changes, wallet positions, and USDC-powered project unlocks.

## 中文介绍

Virtuals Whale Radar 聚焦 Virtuals 新项目发射窗口，展示真实买入事件、分钟级消耗、税率变化、大户榜单、钱包持仓和链上延迟。用户可以先免费浏览项目列表，再用积分解锁真正想长期跟踪的项目。

## 提交版本要求

提交给 Base 生态、Base App 或 Base 相关比赛时，必须使用生产版本，不提交本地测试版本。

- 对外 Demo URL 必须来自 `https://virtuals.club`。
- 截图、录屏和产品说明必须基于生产站真实页面。
- `localhost`、本地 Vite dev、本地测试用户、本地 `0.01 USDC` 测试套餐只能作为内部验收材料，不进入 Base 提交包。
- 生产提交前必须确认 `BILLING_TEST_PLAN_ENABLED=false`，避免对外展示测试套餐。
- 生产提交前必须完成生产健康检查、生产 `/base` 页面检查、生产登录检查和生产 Billing 页面检查。

## 生产 Demo 路径

- 公开欢迎页：`https://virtuals.club/base`
- 统一登录页：`https://virtuals.club/auth/login`
- 邮箱注册页：`https://virtuals.club/auth/register`
- 登录后项目列表：`https://virtuals.club/app/projects`
- 积分与充值：`https://virtuals.club/app/billing`

## Base 集成点

- Base Account 登录：用于 Base App / Coinbase Wallet 用户进入。
- OKX Wallet 登录：用于已安装 OKX Wallet 的 Base 用户进入。
- Base USDC 积分支付：用户通过钱包发起 USDC transfer，后端验 receipt 后自动入账。
- x402 试点：`/.well-known/SKILL.md` 和 `/api/x402/base-signal` 已提供 agentic payment 发现面，当前返回 x402-style `402 Payment Required`，完整 facilitator settlement 后续再补。

## 当前展示案例

欢迎页优先展示 SR 真实发射样本：

- SR 买入事件：602
- 参与钱包：185
- 峰值分钟消耗：约 96.8k V
- 累计税收：约 448.3k V
- 核心案例表：SR 大户榜单，字段为钱包地址、累计花费 V、累计代币数量和含税成本 FDV。

## 截图清单

- 生产 `/base` 欢迎页首屏：突出 Virtuals 项目雷达与 SR 大户榜单。
- 生产 `/auth/login`：展示 Base Account / OKX Wallet / 邮箱登录在同一页。
- 生产 `/app/projects`：展示项目列表与积分解锁入口。
- 生产 `/app/billing`：展示套餐、Base USDC 支付、链上支付记录和未到账找回。

## 上架叙事边界

- 对外英文材料可以使用 Base / Virtuals / SignalHub / USDC 等专有名词。
- 产品内用户文案保持中文优先，避免出现 `buy events / Unique wallets / Peak minute` 这类混杂指标。
- 不承诺代表 Base 官方或 Virtuals 官方；只说明产品在 Base 网络上读取和展示 Virtuals 相关链上数据。
- 普通用户购买积分走 Billing；x402 面向 agent/API 按次购买数据，不作为当前主支付路径。
