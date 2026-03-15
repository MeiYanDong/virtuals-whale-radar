# 页面与接口映射对照

## 目的

这份文档用于同时回答 4 个问题：

1. 旧 `dashboard.html` 里的区块现在分别落到了哪里
2. 旧接口和新接口如何对应
3. 哪些旧接口继续保留兼容，哪些应视为待废弃
4. 管理员端和用户端分别应该调用哪一组接口

## 页面职责对照

| 旧入口 / 旧区块 | 新入口 | 当前职责 | 备注 |
| --- | --- | --- | --- |
| `dashboard.html` 顶部项目切换 | `/admin` / `/app` Top Bar | 统一当前项目上下文 | 通过 `?project=` 持久化 |
| 顶部刷新 / 采集开关 | `/admin` Top Bar | 高频全局动作 | 用户端只保留刷新 |
| 首页运行状态 | `/admin/settings` | 全局 runtime / scheduler / DB 配置 | 不再散落在首页 |
| 首页项目配置表单 | `/admin/projects` | 项目新建、编辑、删除 | 改为折叠列表 + 抽屉 |
| 首页 SignalHub 卡片 | `/admin/signalhub` | upcoming 项目关注入口 | 关注后同步到 Projects |
| 首页分钟图 | `/admin/overview` | 当前活跃项目实时主图 | 从“分析页”转为实时看板 |
| 首页大户榜 | `/admin/overview` | 活跃项目 Whale Board | 只读展示 |
| 首页我的钱包 | `/admin/overview` + `/admin/wallets` | 实时持仓 + 全局钱包维护 | 管理与展示分开 |
| 首页录入延迟 | `/admin/overview` 底部折叠区 | 录入延迟只读明细 | 默认折叠 |
| 普通用户查看项目 | `/app/projects` | 只读项目列表 | 不可编辑 |
| 普通用户看 upcoming | `/app/signalhub` | 只读 upcoming 列表 | 不可关注 |
| 普通用户钱包 | `/app/wallets` | 私有钱包增删改 | 与管理员全局钱包隔离 |
| 普通用户积分 | `/app/billing` | 解锁、充值说明、联系方式二维码、账户动态 | 不接在线支付，也不要求用户在 App 内提充值单 |
| 管理员充值运营 | `/admin/users` | 直接手动入账、积分修正、用户查看 | 当前主流程 |

## 钱包字段评估结论

- `user_wallets` 保留 `is_enabled`
  - 这是用户私有钱包的可启停能力，当前已经落地
- `monitored_wallets` 暂不新增 `is_enabled`
  - 当前管理员全局钱包页只有“增删改名称”的需求
  - 没有单独的“禁用但保留”运营场景
  - 后续若出现“临时停用全局追踪钱包”的实际需求，再扩字段

结论：`is_enabled` 已在用户钱包模型中使用；管理员全局钱包模型当前不扩。

## 接口分层

### 认证层

| 命名空间 | 说明 |
| --- | --- |
| `/api/auth/*` | 登录、注册、登出、当前身份 |

### 管理员层

| 命名空间 | 说明 |
| --- | --- |
| `/api/admin/*` | 项目、SignalHub、全局钱包、用户、运行时、调度器 |

### 用户层

| 命名空间 | 说明 |
| --- | --- |
| `/api/app/*` | 只读项目/SignalHub/Overview、私有钱包、Billing、项目解锁 |

### 兼容层

| 命名空间 | 说明 |
| --- | --- |
| `/health`、`/meta`、`/signalhub/upcoming` 等 | 主要服务旧 `/dashboard` 和历史脚本 |

## 旧接口 -> 新接口 对照

| 旧接口 | 当前是否保留 | 新主入口 | 说明 |
| --- | --- | --- | --- |
| `GET /health` | 保留 | `GET /api/admin/health` | 旧后台兼容；新后台管理员走带前缀接口 |
| `GET /meta` | 保留 | `GET /api/admin/meta` / `GET /api/app/meta` | 管理员与用户已拆分 |
| `GET /signalhub/upcoming` | 保留 | `GET /api/admin/signalhub` / `GET /api/app/signalhub` | 旧接口保留原始 upcoming；新接口补上下文 |
| `GET /launch-configs` | 保留 | `GET /api/admin/launch-configs` | 仅管理员使用 |
| `POST /launch-configs` | 保留 | `POST /api/admin/launch-configs` | 仅管理员使用 |
| `GET /wallet-configs` | 保留 | `GET /api/admin/wallets` / `GET /api/app/wallets` | 新接口已拆成全局钱包与私有钱包 |
| `POST /wallet-configs` | 保留 | `POST /api/admin/wallets` / `POST /api/app/wallets` | 旧接口仅兼容 legacy |
| `POST /wallet-recalc` | 保留 | `POST /api/admin/wallet-recalc` | 用户端不开放 |
| `GET /runtime/pause` | 保留 | `GET /api/admin/runtime/pause` | 仅管理员使用 |
| `POST /runtime/pause` | 保留 | `POST /api/admin/runtime/pause` | 仅管理员使用 |
| `POST /runtime/heartbeat` | 保留 | `POST /api/admin/runtime/heartbeat` | 新后台管理员继续使用 |
| `GET /runtime/db-batch-size` | 保留 | `GET /api/admin/runtime/db-batch-size` | 仅管理员使用 |
| `POST /runtime/db-batch-size` | 保留 | `POST /api/admin/runtime/db-batch-size` | 仅管理员使用 |
| `GET /project-scheduler/status` | 保留 | `GET /api/admin/project-scheduler/status` | 新后台管理入口 |
| `POST /scan-range` | 保留 | `POST /api/admin/scan-range` | 仅管理员使用 |
| `GET /scan-jobs/{id}` | 保留 | `GET /api/admin/scan-jobs/{id}` | 仅管理员使用 |
| `POST /scan-jobs/{id}/cancel` | 保留 | `POST /api/admin/scan-jobs/{id}/cancel` | 仅管理员使用 |
| `GET /mywallets` | 保留 | `GET /api/admin/mywallets` / `GET /api/app/wallets/positions` | 管理员与用户已拆分 |
| `GET /minutes` | 保留 | `GET /api/admin/minutes` | 当前仅管理员需要 |
| `GET /leaderboard` | 保留 | `GET /api/admin/leaderboard` | 当前仅管理员需要 |
| `GET /event-delays` | 保留 | `GET /api/admin/event-delays` | 当前仅管理员需要 |
| `GET /project-tax` | 保留 | `GET /api/admin/project-tax` | 当前仅管理员需要 |

## 管理员端 / 用户端接口映射

### 认证

| 页面 | 接口 |
| --- | --- |
| `/auth/login` | `POST /api/auth/login` |
| `/auth/register` | `POST /api/auth/register` |
| 全局身份恢复 | `GET /api/auth/me` |
| 退出登录 | `POST /api/auth/logout` |

### 用户端

| 页面 | 读取接口 | 写入接口 |
| --- | --- | --- |
| `/app/overview` | `GET /api/app/overview-active` | `POST /api/app/projects/{id}/unlock` |
| `/app/projects` | `GET /api/app/projects` | 无 |
| `/app/signalhub` | `GET /api/app/signalhub` | 无 |
| `/app/wallets` | `GET /api/app/wallets`、`GET /api/app/wallets/positions` | `POST /api/app/wallets`、`PATCH /api/app/wallets/{id}`、`DELETE /api/app/wallets/{id}` |
| `/app/billing` | `GET /api/app/billing/summary`、`GET /api/app/notifications` | `POST /api/app/notifications/{id}/read`、`POST /api/app/notifications/read-all` |

### 管理员端

| 页面 | 读取接口 | 写入接口 |
| --- | --- | --- |
| `/admin/overview` | `GET /api/admin/overview-active` | 无 |
| `/admin/projects` | `GET /api/admin/projects` | `POST /api/admin/projects`、`DELETE /api/admin/projects/{id}`、`POST /api/admin/scan-range` |
| `/admin/signalhub` | `GET /api/admin/signalhub` | `POST /api/admin/projects` 或 `POST /api/admin/signalhub/watchlist/*` |
| `/admin/wallets` | `GET /api/admin/wallets`、`GET /api/admin/mywallets` | `POST /api/admin/wallets`、`DELETE /api/admin/wallets/{wallet}`、`POST /api/admin/wallet-recalc` |
| `/admin/users` | `GET /api/admin/users`、`GET /api/admin/users/{id}`、`GET /api/admin/users/{id}/wallets`、`GET /api/admin/users/{id}/credit-ledger`、`GET /api/admin/users/{id}/project-access` | `POST /api/admin/users/{id}/status`、`POST /api/admin/users/{id}/reset-password`、`POST /api/admin/users/{id}/credits/adjust`、`POST /api/admin/users/{id}/credits/topup`、`POST /api/admin/users/{id}/wallets/{wallet_id}/status`、`DELETE /api/admin/users/{id}/wallets/{wallet_id}` |
| `/admin/settings` | `GET /api/admin/meta`、`GET /api/admin/health`、`GET /api/admin/project-scheduler/status`、`GET /api/admin/runtime/pause`、`GET /api/admin/runtime/db-batch-size`、`GET /api/admin/legacy-apis` | `POST /api/admin/runtime/pause`、`POST /api/admin/runtime/heartbeat`、`POST /api/admin/runtime/db-batch-size` |

## Legacy 收口规则

- 旧 `/dashboard` 仍可继续工作，但 legacy API 现在被明确标记为兼容层。
- 除 `/health` 外，其余 legacy 管理型路由统一要求 `admin` 身份。
- legacy 路由现在会返回：
  - `X-VWR-Legacy-Api: true`
  - `X-VWR-Legacy-State: compatible`
  - `X-VWR-Replacement: /api/...`
  - `X-VWR-Legacy-Access: admin/public`
- `/api/admin/legacy-apis` 提供运行时清单，便于 Settings 或脚本查看当前兼容层边界。

## 运营效率补充

- `billing_requests` 现在专门承接线下充值申请：
  - `proof_storage_key`
  - `proof_original_name`
  - `proof_content_type`
  - `proof_size`
  - `status`
  - `admin_note`
- 付款凭证不再只是文本字段，而是图片附件归档，用户与管理员都可以通过专用 proof 接口查看。
- `user_notifications` 现在承接用户站内通知：
  - 注册赠送
  - 充值已到账
  - 手工调账
  - 项目解锁
- 用户顶栏新增通知入口，支持：
  - 未读数量提醒
  - 单条已读
  - 全部已读
- 当前产品主流程不暴露充值申请页，用户微信付款后由管理员直接在 `Users` 页手动入账。
- `billing_requests` / proof / notify 这组接口仍保留为备用能力，但不再作为当前 UI 主流程。

## 可回放验收样本

- replay fixture 脚本：`scripts/seed_wallet_positions_fixture.py`
- 验证脚本：`scripts/verify_wallet_tracking_name.py`
- 这组样本用于重复验证：
  - `wallet_positions` 是否能在 `Overview.trackedWallets` 正常展示
  - 钱包名称修改后是否同步反映到追踪钱包列表

## 待废弃接口清单

下面这些接口仍然保留，是为了兼容旧 `/dashboard` 或已有脚本；新代码不应继续优先接入它们：

- `/health`
- `/meta`
- `/signalhub/upcoming`
- `/launch-configs`
- `/wallet-configs`
- `/wallet-recalc`
- `/runtime/*`
- `/project-scheduler/status`
- `/scan-range`
- `/scan-jobs/*`
- `/mywallets`
- `/minutes`
- `/leaderboard`
- `/event-delays`
- `/project-tax`

建议策略：

1. 新前端只走 `/api/auth/*`、`/api/app/*`、`/api/admin/*`
2. 旧 `/dashboard` 继续消费 legacy 接口
3. 等旧后台彻底下线后，再决定移除 legacy 路由

## 本轮验收结论

- 主链路 `SignalHub -> 关注 -> Projects -> 调度 -> Overview` 已在隔离环境 `18084` 跑通
- `resolved_end_at` 已实测符合：
  - `manual_end_at`
  - `signalhub_end_at`
  - `start_at + 99 分钟`
- 项目开始前 30 分钟预热、回扫任务入队、图表时间窗口同步均已实测通过
- 用户端只读边界与私有钱包 CRUD 已实测通过
- replay fixture 已补齐，`钱包名称编辑后影响追踪展示` 已在隔离环境 `18084` 实测通过
- legacy 路由现已带弃用头，并对管理型 legacy 路由增加了 `admin` 权限收口
- 充值入账的实付金额、付款凭证与用户通知链路已实测通过
- 图片凭证上传、附件访问、未读通知提醒与 `Operations` 处理流已在隔离环境 `18085` 实测通过
- 轻模式已在隔离环境 `18086` 实测通过：隐藏充值申请后，用户端只看到最简通知；管理员继续可直接手动入账
