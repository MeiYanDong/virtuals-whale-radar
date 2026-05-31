# Virtuals Whale Radar 管理后台迭代执行清单

> 基于 [PLAN.md](/D:/20_Projects/virtuals-whale-radar/docs/PLAN.md) 拆解。  
> 本清单用于跟踪“迭代版信息架构”落地进度。  
> 说明：保留仍然有效的现有基线为已完成；所有新架构下尚未落地的任务恢复为未完成。

## 已确认决策

- [x] 品牌名称统一为 `Virtuals Whale Radar`。
- [x] 左侧栏一级导航调整为 `Overview / Projects / SignalHub / Wallets / Settings`。
- [x] `Overview` 只展示正在发射项目的实时数据，不承担编辑。
- [x] `Projects` 承担项目新建、删除、编辑、采集、回扫和状态展示。
- [x] `SignalHub` 作为关注列表入口，勾选项目后自动进入 `Projects`。
- [x] `Wallets` 独立为一级页面，只管理 `钱包地址 + 名称`。
- [x] `Settings` 仅保留全局设置，不放用户配置。
- [x] 结束时间优先级为：`管理员手动设置 > SignalHub > 开始时间 + 99 分钟`。
- [x] `+99` 的单位确认为 `99 分钟`。
- [x] `SpentV` 柱状图放在 `Overview` 项目头下方，作为实时主图。
- [x] 删除项目的语义固定为：`取消关注 + 从 Projects 移除 + 停止调度 + 保留历史数据`。
- [x] 未登录访问业务页时统一跳转 `/base?redirect=...`，Base 欢迎页作为公开入口。
- [x] 用户端固定为 `Overview / Projects / SignalHub / Wallets / Billing` 五页。
- [x] 管理员端新增 `Users` 页面。
- [x] 用户端只有 `Wallets` 可编辑，其余页面只读。
- [x] 用户钱包数据彼此隔离，管理员可查看全部用户钱包。
- [x] 管理员默认不直接查看完整密码哈希，只提供密码状态和重置能力。
- [x] 初始管理员账号通过配置或环境变量 bootstrap 创建。
- [x] 用户查看某个项目 `Overview` 详细数据时，按“每用户、每项目首次解锁”扣 `20` 积分，解锁后永久可看。
- [x] 新用户注册赠送 `20` 积分。
- [x] 充值方案固定为：`20 积分 = 20 元 / 2.00 USDC`、`100 积分 = 80 元 / 8.00 USDC`。
- [x] 用户端 `Projects / SignalHub` 免费可看，未解锁项目的 `Overview` 详细数据不可看。
- [x] 用户积分不足时，点击未解锁项目应引导到 `Billing`。
- [x] `Billing` 页面以 Base USDC 自动支付为主，联系方式二维码作为支付失败/未到账时的帮助入口。
- [x] `Billing` 顶部固定展示 Virtuals 邀请码边界与注册链接。
- [x] 管理员调整积分时只允许“加积分 / 扣积分 + 备注”，不直接裸改余额。
- [x] 管理员端补充 `Operations` 一级页面，用于处理充值申请和通知流转。
- [x] 用户提交充值申请时必须上传图片凭证，后端按附件归档保存。
- [x] 用户通知支持 `未读 / 已读 / 全部已读`，并在顶栏显示未读提醒。
- [x] 当前默认充值流程改为：Base USDC 自动入账；微信付款后管理员手动入账保留为备用。

## 当前有效基线

- [x] `frontend/admin/` 已存在，可作为本轮迭代基础工程。
- [x] `/admin` 静态托管、SPA 刷新回退与旧 `/dashboard` 共存能力已存在。
- [x] `React + Vite + TypeScript + Tailwind + shadcn/ui` 技术栈已接入。
- [x] 当前已具备 `Overview / Projects / SignalHub / Wallets / Operations` 页面基线，可重构而非重搭。
- [x] `SignalHub` API 代理与基础拉取能力已存在。
- [x] 当前主题、图标和品牌资源链路已可复用，但需要按新品牌文案和布局再调整。

## Phase 0：文档与范围冻结

- [x] 将迭代版信息架构、五页职责、状态机和调度时序回写到 `docs/PLAN.md`。
- [x] 将旧版“已全部完成”的执行清单替换为新的迭代任务清单。
- [x] 补一版“旧页面到新页面”的字段迁移对照，明确哪些旧模块被删除、合并或下沉。
- [x] 补一版“现有 API / 新 API / 待废弃 API”对照表，避免实现中反复返工。

## Phase 1：壳层重构

- [x] 将左侧栏调整为最终一级导航：`Overview / Projects / SignalHub / Wallets / Settings`。
- [x] 移除 `Legacy Dashboard`、`Operations` 作为一级导航项的现状。
- [x] 实现桌面端左侧栏三态：`Expanded / Rail / Hidden`。
- [x] 将左侧栏状态持久化到 `localStorage`。
- [x] 将顶部品牌文案全部替换为 `Virtuals Whale Radar`。
- [x] 将当前品牌展示由 `V-Pulse` 全量替换为新品牌。
- [x] 精简 `Top Bar`，只保留品牌、侧栏切换、活跃项目切换、runtime 状态、刷新。
- [x] 删除侧栏和顶栏中重复的状态摘要与说明性文案。
- [x] 调整默认路由逻辑：存在活跃项目时默认进入 `Overview`，否则默认进入 `Projects`。

## Phase 2：数据模型与后端基础改造

- [x] 设计并创建 `managed_projects` 表。
- [x] 为 `managed_projects` 增加字段：
  - `name`
  - `signalhub_project_id`
  - `detail_url`
  - `token_addr`
  - `internal_pool_addr`
  - `start_at`
  - `signalhub_end_at`
  - `manual_end_at`
  - `resolved_end_at`
  - `is_watched`
  - `collect_enabled`
  - `backfill_enabled`
  - `status`
  - `source`
  - `created_at`
  - `updated_at`
- [x] 确定 `launch_configs` 与 `managed_projects` 的同步规则。
- [x] 扩展钱包表，为钱包增加 `name` 字段。
- [x] 评估是否增加钱包启用状态字段 `is_enabled`。
- [x] 为项目状态定义统一枚举：`draft / scheduled / prelaunch / live / ended / removed`。
- [x] 为项目结束时间实现统一解析逻辑：`manual > signalhub > start + 99m`。

## Phase 3：后端 API 改造

- [x] 新增 `managed_projects` 列表接口。
- [x] 新增 `managed_projects` 创建接口。
- [x] 新增 `managed_projects` 编辑接口。
- [x] 新增 `managed_projects` 删除接口。
- [x] 新增 `SignalHub` 加入关注接口。
- [x] 新增 `SignalHub` 取消关注接口。
- [x] 新增 `SignalHub` 批量加入关注接口。
- [x] 新增 `SignalHub` 批量取消关注接口。
- [x] 新增 `Wallets` CRUD 接口，并支持 `name` 字段。
- [x] 新增 `Overview` 专用聚合接口，返回：
  - 活跃项目头信息
  - `SpentV` 柱状图数据
  - Whale Board
  - 追踪钱包持仓
  - 交易录入延迟
- [x] 新增项目调度状态读取接口。
- [x] 为 `Projects` 行展开态提供统一项目详情接口。

## Phase 4：自动调度器

- [x] 增加项目调度器循环。
- [x] 让调度器按固定频率扫描 `scheduled / prelaunch / live` 项目。
- [x] 在 `start_at - 30 分钟` 自动将项目切换为 `prelaunch`。
- [x] 在 `prelaunch` 阶段自动触发该项目的采集准备。
- [x] 在 `prelaunch` 阶段自动触发该项目回扫。
- [x] 在 `prelaunch` 阶段自动设置项目默认分钟图区间为 `[start_at, resolved_end_at]`。
- [x] 在 `start_at` 将项目切换为 `live`。
- [x] 在 `resolved_end_at` 将项目切换为 `ended`。
- [x] 在项目删除时停止该项目调度。
- [x] 处理边界情况：
  - 关注时已进入预热窗口
  - 关注时项目已开始
  - 关注时项目已结束

## Phase 5：Overview 页面重构

- [x] 将 `Overview` 改成“当前活跃项目实时看板”，移除旧版系统总览逻辑。
- [x] 顶部增加活跃项目切换器。
- [x] 实现项目头信息区，展示：
  - 项目名称
  - 开始时间
  - 结束时间
  - 项目详情链接
  - 代币地址
  - 内盘地址
  - 当前项目累计税收
- [x] 在项目头下实现 `SpentV` 实时柱状图。
- [x] 将 `累计 SpentV`、`峰值分钟` 与分钟柱状图顶部数值统一改为整数展示。
- [x] 将图表默认时间区间绑定到项目 `start_at / resolved_end_at`。
- [x] 重构 Whale Board，字段固定为：
  - 钱包地址
  - 累计花费 V
  - 累计代币数量（万）
  - 买入市值（万 USD）
  - 更新时间
- [x] 在 Whale Board 下方实现“追踪钱包持仓”，字段与 Whale Board 完全一致。
- [x] 将交易录入延迟放到页面底部并默认折叠。
- [x] 移除 `Overview` 中所有项目编辑能力。
- [x] 清理 `Overview` 中重复的 KPI 卡、快捷入口、说明块和无关运维块。
- [x] 完成 `Overview` 的 loading / empty / error / no-active-project 状态。

## Phase 6：Projects 页面重构

- [x] 将 `Projects` 从“单项目工作区”改为“项目管理列表页”。
- [x] 页面顶部增加 `新建项目` 按钮。
- [x] 页面顶部增加 `删除项目` 按钮，并支持批量删除。
- [x] 列表每行展示：
  - 项目名称
  - 开始时间
  - 结束时间
  - 项目详情
  - 当前状态
  - 选择框
  - 折叠按钮
- [x] 每个项目支持折叠展开。
- [x] 展开后展示：
  - 代币地址
  - 内盘地址
  - 运行状态
  - `采集` 按钮
  - `回扫` 按钮
  - `编辑` 按钮
- [x] 明确 `采集` 按钮对应 `collect_enabled`。
- [x] 明确 `回扫` 按钮对应“按项目时间窗口立即发起回扫”。
- [x] 将项目编辑抽屉/弹窗绑定到 `managed_projects`。
- [x] 实现项目手动创建流程。
- [x] 实现批量删除流程，并确保语义符合已确认规则。

## Phase 7：SignalHub 页面重构

- [x] 将 `SignalHub Inbox` 重命名为 `SignalHub`。
- [x] 将主心智从“导入”改成“关注列表”。
- [x] 在列表中加入勾选框与全选能力。
- [x] 每行展示：
  - 项目名称
  - 开始时间
  - 解析后的结束时间
  - 项目详情
  - 字段完整度
  - 当前关注状态
- [x] 实现单项目加入关注。
- [x] 实现单项目取消关注。
- [x] 实现批量加入关注。
- [x] 实现批量取消关注。
- [x] 勾选关注后立即写入 `managed_projects`。
- [x] 勾选关注后立即同步到 `Projects`。
- [x] 字段缺失项目进入 `draft`。
- [x] 字段完整项目进入 `scheduled`。

## Phase 8：Wallets 页面重构

- [x] 将 `Wallets` 作为正式一级页面纳入新架构，而不是沿用旧逻辑拼接。
- [x] 钱包列表展示：
  - 名称
  - 钱包地址
  - 编辑
  - 删除
- [x] 实现新增钱包流程。
- [x] 实现编辑钱包流程。
- [x] 实现删除钱包流程。
- [x] 让 `Overview` 的追踪钱包持仓严格使用这里维护的钱包列表。

## Phase 9：Settings 页面实现

- [x] 新增 `Settings` 页面或设置面板。
- [x] 将全局固定参数迁移到 `Settings`。
- [x] 将 `DB_BATCH_SIZE` 控制迁移到 `Settings`。
- [x] 将极速模式 / 超速模式控制迁移到 `Settings`。
- [x] 将全局 runtime 状态展示迁移到 `Settings`。
- [x] 将调度器状态展示迁移到 `Settings`。
- [x] 删除其它页面中重复出现的全局设置控件。

## Phase 10：前端状态与交互收敛

- [x] 重新定义“当前活跃项目”状态来源，优先服务 `Overview`。
- [x] 将 `Projects` 与 `SignalHub` 的选中状态拆开，避免共享一个模糊的 `selectedProject`。
- [x] 将项目默认分钟图区间改为来自后端调度状态，而不是页面本地临时选择。
- [x] 清理页面中重复的 toast、inline message、状态 badge 逻辑。
- [x] 为删除项目、取消关注等危险操作补齐确认流程。
- [x] 清理当前新后台中多余的解释性文案与重复的摘要块。
- [x] 修复右侧抽屉长内容无法滚动的问题，确保 `Users / Projects / SignalHub` 详情抽屉都可纵向滚动查看完整内容。
- [x] 统一 `Projects / SignalHub / Users` 抽屉结构为“内容区独立滚动 + 底部操作区固定”。

## Phase 11：品牌与视觉收尾

- [x] 将页面标题、品牌区、空状态文案中的 `V-Pulse` 全量替换为 `Virtuals Whale Radar`。
- [x] 将左侧栏品牌块改成最终品牌展示方案。
- [x] 检查图标和 favicon 是否仍使用旧命名或旧文案。
- [x] 清理和新信息架构不一致的卡片、标题、副标题与提示文本。
- [x] 调整页面层级，避免同一状态在侧栏、顶栏、正文中重复出现。
- [x] 为 `Projects / SignalHub` 抽屉补齐隐藏的 `DialogTitle / DialogDescription`，清理控制台无障碍警告。

## Phase 12：联调与验收

- [x] 验证 `SignalHub -> 关注 -> Projects -> 调度 -> Overview` 主链路。
- [x] 验证结束时间解析逻辑严格符合：
  - `manual_end_at`
  - `signalhub_end_at`
  - `start_at + 99 分钟`
- [x] 验证项目开始前 30 分钟能自动触发预热。
- [x] 验证 `Overview` 中的图表区间自动同步到项目时间窗口。
- [x] 验证删除项目后：
  - 不再出现在 `Projects`
  - 不再参与调度
  - 历史数据仍保留
- [x] 验证钱包名称编辑后能正确影响追踪钱包展示。
- [x] 验证左侧栏隐藏/收窄/展开三态均正常。
- [x] 验证 `Overview / Projects / SignalHub / Wallets / Settings` 五页没有重复 UI 和错位职责。

## Phase 13：认证与角色体系

- [x] 新增 `users` 表。
- [x] 新增 `user_sessions` 表。
- [x] 为 `users` 增加字段：
  - `nickname`
  - `email`
  - `password_hash`
  - `role`
  - `status`
  - `password_updated_at`
  - `last_login_at`
  - `created_at`
  - `updated_at`
- [x] 为 `user_sessions` 增加字段：
  - `user_id`
  - `token_hash`
  - `user_agent`
  - `ip_addr`
  - `last_seen_at`
  - `expires_at`
  - `revoked_at`
  - `created_at`
  - `updated_at`
- [x] 接入密码哈希方案，默认使用 `Argon2id`。
- [x] 增加初始管理员 bootstrap 逻辑。
- [x] 新增认证接口：
  - `/api/auth/register`
  - `/api/auth/login`
  - `/api/auth/logout`
  - `/api/auth/me`
- [x] 增加 session middleware。
- [x] 增加 `require_auth` 守卫。
- [x] 增加 `require_admin` 守卫。
- [x] 完成未登录跳转 `/base?redirect=...`。
- [x] 完成用户访问 `/admin/*` 跳转 `/app`。
- [x] 完成管理员访问 `/app/*` 跳转 `/admin`。

## Phase 14：用户私有钱包模型

- [x] 新增 `user_wallets` 表。
- [x] 为 `user_wallets` 增加字段：
  - `user_id`
  - `wallet`
  - `name`
  - `is_enabled`
  - `created_at`
  - `updated_at`
- [x] 保留现有 `monitored_wallets` 作为管理员全局钱包表。
- [x] 确认用户钱包与管理员钱包完全分离，不共用同一张表。
- [x] 新增用户钱包 CRUD 接口：
  - `GET /api/app/wallets`
  - `POST /api/app/wallets`
  - `PATCH /api/app/wallets/{id}`
  - `DELETE /api/app/wallets/{id}`
- [x] 新增用户钱包持仓接口 `GET /api/app/wallets/positions`。
- [x] 让用户 `Overview` 的追踪钱包区只使用当前用户的钱包。
- [x] 保证用户之间无法互相读取钱包数据。

## Phase 15：用户端五页

- [x] 新增用户端路由壳层 `/app/*`。
- [x] 新增用户端导航：`Overview / Projects / SignalHub / Wallets`。
- [x] 新增用户端导航项 `Billing`。
- [x] 新增用户端 `Overview` 页面。
- [x] 新增用户端 `Projects` 页面。
- [x] 新增用户端 `SignalHub` 页面。
- [x] 复用或重建用户端 `Wallets` 页面。
- [x] 新增用户端 `Billing` 页面。
- [x] 删除用户端中所有项目编辑按钮。
- [x] 删除用户端中所有删除项目按钮。
- [x] 删除用户端中所有 SignalHub 勾选和关注按钮。
- [x] 删除用户端中所有采集 / 回扫 / 全局设置入口。
- [x] 保证用户端 `Projects` 只显示可公开阅读项目，不显示 `draft / removed`。
- [x] 保证用户端 `SignalHub` 只读。

## Phase 19：积分模型与解锁机制

- [x] 为 `users` 增加积分字段：
  - `credit_balance`
  - `credit_spent_total`
  - `credit_granted_total`
- [x] 新增 `credit_ledger` 表。
- [x] 为 `credit_ledger` 增加字段：
  - `user_id`
  - `delta`
  - `balance_after`
  - `type`
  - `source`
  - `project_id`
  - `note`
  - `operator_user_id`
  - `created_at`
- [x] 新增 `user_project_access` 表。
- [x] 为 `user_project_access` 增加字段：
  - `user_id`
  - `project_id`
  - `unlock_cost`
  - `source`
  - `unlocked_at`
  - `expires_at`
  - `created_at`
- [x] 注册成功后自动发放 `20` 积分。
- [x] 将注册赠送写入 `credit_ledger(type=signup_bonus)`。
- [x] 实现“每用户、每项目首次解锁扣 `10` 积分”的事务逻辑。
- [x] 保证同一用户对同一项目不会重复扣分。
- [x] 新增项目访问守卫，限制普通用户访问未解锁项目的 `Overview`。
- [x] 管理员默认拥有全部项目访问权限，不受积分限制。
- [x] 新增用户端项目解锁接口：
  - `GET /api/app/projects/{id}/access`
  - `POST /api/app/projects/{id}/unlock`
- [x] 新增用户端计费摘要接口 `GET /api/app/billing/summary`。
- [x] 在 `app/projects` 与 `app/signalhub` 返回解锁状态字段：
  - `is_unlocked`
  - `unlock_cost`
  - `can_unlock_now`

## Phase 20：Billing 页面与管理员积分运营

- [x] 在用户端 Sidebar 增加 `Billing` 一级入口。
- [x] 新增 `Billing` 页面顶部公告条：
  - `如果你还没有 Virtuals 账号，可以先用邀请码完成注册；这里的积分只用于解锁 Whale Radar 项目看板。`
  - `https://app.virtuals.io/referral?code=LFfW5x`
- [x] 在 `Billing` 页面展示：
  - 当前积分
  - 累计消耗积分
  - 已解锁项目数
- [x] 在 `Billing` 页面展示固定套餐：
  - `20 积分 / 20 元 / 2.00 USDC`
  - `100 积分 / 80 元 / 8.00 USDC`
- [x] 在 `Billing` 页面展示联系方式二维码与联系说明。
- [x] 用户点击购买时优先走 Base USDC 自动入账，二维码只作为支付失败/未到账时的帮助入口。
- [x] 用户点击未解锁项目时：
  - 积分足够则弹确认框解锁
  - 积分不足则引导去 `Billing`
- [x] 管理员 `Users` 列表新增字段：
  - 当前积分
  - 累计消耗积分
  - 已解锁项目数
- [x] 管理员用户详情新增：
  - 当前积分
  - 累计消耗
  - 积分流水
  - 已解锁项目列表
- [x] 新增管理员积分接口：
  - `GET /api/admin/users/{id}/credit-ledger`
  - `GET /api/admin/users/{id}/project-access`
  - `POST /api/admin/users/{id}/credits/adjust`
  - `POST /api/admin/users/{id}/credits/topup`
- [x] 管理员只允许“加积分 / 扣积分 + 备注”，不直接裸改余额。
- [x] 管理员积分录入前端增加整数校验，避免无效输入直接触发后端报错。
- [x] 管理员积分运营区收敛为“线下充值入账”主入口 + “手工修正积分”折叠次级入口。

## Phase 21：商业模式联调与验收

- [x] 验证新用户注册后默认获得 `20` 积分。
- [x] 验证用户首次解锁项目时扣除 `10` 积分。
- [x] 验证同一用户再次访问同一项目不会重复扣分。
- [x] 验证积分不足时无法查看未解锁项目 `Overview`，并会引导到 `Billing`。
- [x] 验证用户端 `Projects / SignalHub` 免费可看，但不泄露未解锁项目详细数据。
- [x] 验证 `Billing` 页面能显示余额、套餐、邀请链接和联系方式二维码。
- [x] 验证管理员手动加积分后，用户端余额立即更新。
- [x] 验证管理员手动扣积分后，流水和累计消耗保持正确。
- [x] 验证管理员能看到用户已解锁项目列表。
- [x] 验证管理员积分录入对非法整数输入会被前端拦截，后端也返回明确字段错误。

## Phase 22：Legacy 收口与运营效率补强

- [x] 新增可回放的 `wallet_positions` fixture 脚本，便于重复验收 `Overview` 追踪钱包展示。
- [x] 使用 replay fixture 实测通过“钱包名称编辑后影响 trackedWallets 展示”链路。
- [x] 新增 `/api/admin/legacy-apis` 清单接口，明确 legacy 路由兼容状态。
- [x] 为 legacy 路由增加弃用响应头，返回替代接口信息。
- [x] 将 legacy 管理型接口收口为 `admin` 权限，避免继续裸露给未登录或普通用户。
- [x] 为充值流水增加结构化字段：
  - `payment_amount`
  - `payment_proof_ref`
- [x] 管理员 `Users` 积分运营区支持录入实付金额、付款凭证和备注。
- [x] 用户 `Billing` 页面新增最近通知/账户动态区。
- [x] 用户 `Projects / SignalHub` 页面新增积分解锁转化提示。

## Phase 23：凭证附件、通知中心与充值处理流

- [x] 新增 `billing_requests` 表，保存用户充值申请、状态流转和凭证元数据。
- [x] 新增 `user_notifications` 表，保存站内通知、已读状态和跳转入口。
- [x] 将用户 `Billing` 的付款凭证从文本字段升级为图片上传。
- [x] 为付款凭证增加用户侧与管理员侧附件访问接口。
- [x] 用户提交充值申请后，自动生成 `pending_review` 状态记录。
- [x] 用户提交充值申请后，自动生成一条“付款凭证已提交”的未读通知。
- [x] 顶栏增加用户通知提醒入口，并展示未读数量。
- [x] 用户通知支持单条已读。
- [x] 用户通知支持全部已读。
- [x] 管理员端重新引入 `Operations` 一级页面，专门处理充值申请。
- [x] `Operations` 页面支持按状态筛选 `pending_review / credited / notified`。
- [x] `Operations` 页面详情抽屉支持预览付款凭证图片。
- [x] 管理员可在 `Operations` 中执行“确认入账”，将申请推进到 `credited`。
- [x] 管理员可在 `Operations` 中执行“标记已通知用户”，将申请推进到 `notified`。
- [x] 验证链路：用户上传图片凭证 -> 管理员确认入账 -> 管理员标记已通知用户 -> 用户收到未读通知并可读。

## Phase 24：充值流程轻量化收敛

- [x] 用户端 `Billing` 移除付款凭证上传区。
- [x] 用户端 `Billing` 移除充值申请记录区。
- [x] 用户端 `Billing` 保留为：积分摘要、套餐、联系方式二维码、到账说明、账户动态。
- [x] 管理员端移除 `Operations` 一级导航入口。
- [x] `/admin/operations` 改为跳转回 `Users`，不再作为常规入口暴露。
- [x] 管理员在 `Users` 页直接执行“微信付款后手动入账”。
- [x] `Users` 页手动入账表单移除“付款凭证”文本字段。
- [x] 用户端通知范围收窄为：注册赠送、积分到账、人工调账、项目解锁。
- [x] 即使保留 `billing_requests` 后端能力，用户端未读数和通知列表也不再展示 `billing_request_submitted / billing_request_notified`。
- [x] 验证轻流程：注册赠送可见、隐藏充值申请不会污染通知中心、管理员入账后用户能看到到账提醒。

## Phase 25：历史项目详情回看

- [x] 保留 `Projects` 里的 `ended` 项目，不因项目结束而从用户列表移除。
- [x] 新增用户端历史项目详情读取接口 `GET /api/app/projects/{id}/overview`。
- [x] 历史项目详情接口复用积分解锁门禁，未解锁时继续返回 `project_locked`。
- [x] 用户端从 `Projects` 打开 `ended` 项目时，进入独立的历史详情页。
- [x] 历史详情页展示分钟图、大户榜、追踪钱包持仓、交易录入延迟。
- [x] 历史详情页与活跃项目看板复用同一套聚合字段与展示标准。

## Phase 16：管理员 Users 页面

- [x] 管理员端导航增加 `Users`。
- [x] 新增 `GET /api/admin/users`。
- [x] 新增 `GET /api/admin/users/{id}`。
- [x] 新增 `GET /api/admin/users/{id}/wallets`。
- [x] 新增 `POST /api/admin/users/{id}/status`。
- [x] 新增 `POST /api/admin/users/{id}/reset-password`。
- [x] 可选新增用户钱包管理接口：
  - `POST /api/admin/users/{id}/wallets/{wallet_id}/status`
  - `DELETE /api/admin/users/{id}/wallets/{wallet_id}`
- [x] 新增管理员 `Users` 页面列表。
- [x] 在 `Users` 页面展示：
  - 昵称
  - 注册邮箱
  - 角色
  - 状态
  - 钱包数量
  - 最近登录时间
  - 注册时间
- [x] 新增用户详情抽屉。
- [x] 在详情抽屉展示：
  - 基本资料
  - 密码状态
  - 用户钱包列表
  - 禁用/启用操作
  - 重置密码操作

## Phase 17：前后端接口拆分

- [x] 将当前无前缀接口逐步拆分为：
  - `/api/auth/*`
  - `/api/app/*`
  - `/api/admin/*`
- [x] 新增 `/api/app/meta`。
- [x] 新增 `/api/app/overview-active`。
- [x] 新增 `/api/app/projects`。
- [x] 新增 `/api/app/signalhub`。
- [x] 新增 `/api/admin/meta`。
- [x] 评估哪些旧接口保留兼容，哪些标记待废弃。
- [x] 补一版管理员端与用户端接口映射表。

## Phase 18：双角色联调与验收

- [x] 验证注册 -> 邮箱验证 -> 自动登录 -> 进入 `/app`。
- [x] 验证未登录访问 `/app/*` 与 `/admin/*` 会跳到 `/base?redirect=...`。
- [x] 验证普通用户无法访问管理员写接口。
- [x] 验证普通用户无法看到其它用户钱包。
- [x] 验证用户端 `Overview / Projects / SignalHub` 全只读。
- [x] 验证用户端 `Wallets` 可新增、编辑、删除自己的钱包。
- [x] 验证管理员端 `Users` 能看到用户列表和用户钱包。
- [x] 验证管理员重置密码后用户可用新密码登录。
- [x] 验证管理员禁用用户后该用户无法继续访问业务页。

## 完成定义

- [x] 左侧栏完成最终五页导航结构，并支持隐藏。
- [x] `Overview` 成为只读活跃项目实时看板。
- [x] `Projects` 成为项目管理页。
- [x] `SignalHub` 成为关注列表入口，并自动同步到 `Projects`。
- [x] `Wallets` 成为独立一级页面。
- [x] `Settings` 成为唯一全局设置入口。
- [x] 项目自动调度逻辑生效。
- [x] 品牌名称与页面结构全部符合 `Virtuals Whale Radar` 迭代版方案。
- [x] 用户端 `/app` 五页可用。
- [x] 认证与会话体系可用。
- [x] 管理员端 `Users` 页面可用。
- [x] 用户钱包完成私有隔离。
- [x] 积分与项目解锁机制可用。
- [x] `Billing` 页面与管理员积分管理可用。
- [x] 图片凭证上传、通知中心与管理员充值处理流可用。
- [x] 充值链路已升级为“Base USDC 自动入账 + 微信/管理员手动入账备用”的模式。
- [x] 用户可以从 `Projects` 回看 `ended` 项目的历史详情。
- [x] 公开注册改为“邮箱验证成功后再创建用户并发放注册积分”。

## Phase 26：邮箱验证注册闭环

- [x] 新增 `pending_registrations` 表。
- [x] 为 `users` 增加：
  - `email_verified_at`
  - `signup_ip`
  - `signup_device_fingerprint`
  - `signup_bonus_granted_at`
- [x] `POST /api/auth/register` 改为只创建待验证注册，不立即写入 `users`。
- [x] 注册成功后发送邮箱验证邮件。
- [x] 新增 `POST /api/auth/resend-verification`。
- [x] 新增 `GET /api/auth/verify-email`。
- [x] 验证成功后再正式创建本地用户。
- [x] 验证成功后写入 `signup_bonus` 积分流水并发放 `20` 积分。
- [x] 验证成功后自动创建 session 并登录。
- [x] `POST /api/auth/login` 对未验证邮箱返回 `email_not_verified`。

## Phase 27：邮箱验证前端与配置

- [x] `config.example.json` 增加邮件发送相关配置项：
  - `APP_PUBLIC_BASE_URL`
  - `EMAIL_ENABLED`
  - `EMAIL_SMTP_HOST`
  - `EMAIL_SMTP_PORT`
  - `EMAIL_SMTP_USERNAME`
  - `EMAIL_SMTP_PASSWORD`
  - `EMAIL_SMTP_USE_TLS`
  - `EMAIL_FROM_ADDRESS`
  - `EMAIL_FROM_NAME`
  - `EMAIL_VERIFY_TOKEN_TTL_SEC`
- [x] 注册页改为“提交后提示查收验证邮件”，不再立即登录。
- [x] 登录页支持提示“邮箱未验证”，并提供重发验证邮件入口。
- [x] 新增邮箱验证结果页或结果态。
- [x] 验证注册链接打开成功后跳转 `/app`。
- [x] 补邮件文案与用户提示，明确“验证成功后才会到账 20 积分”。

## Phase 28：生产 HTTPS 与邮件链接切换

- [x] 使用阿里云免费测试证书为 `virtuals.club` 申请 DV 证书。
- [x] 证书签发后将证书文件保存在本地 `secrets/ssl/`，并避免被 Git 跟踪。
- [x] 生产服务器部署 `virtuals.club.pem` 与 `virtuals.club.key`。
- [x] Nginx 新增 `443` 监听，并对 `virtuals.club` 与 `www.virtuals.club` 开启 HTTPS。
- [x] `80` 端口自动跳转到 `https://virtuals.club`。
- [x] 生产配置中的 `APP_PUBLIC_BASE_URL` 切换到 `https://virtuals.club`。
- [x] 验证 `https://virtuals.club/auth/login` 与 `https://www.virtuals.club/auth/login` 返回正常。
- [x] 验证邮箱注册链接在生产环境改为 HTTPS 域名。

## Phase 29：列表与历史详情收尾

- [x] `Projects` 页面新增关键词搜索。
- [x] `Projects` 搜索覆盖项目名称、详情链接、代币地址和内盘地址。
- [x] `Projects` 页面按状态固定分组为：
  - `待执行与进行中`
  - `已结束`
- [x] `已结束` 项目默认折叠。
- [x] 管理员为项目列表新增“查看仪表盘/历史详情”入口。
- [x] 新增管理员历史详情路由 `/admin/projects/{id}`。
- [x] 新增管理员历史详情接口 `/api/admin/projects/{id}/overview`。
- [x] 管理员可查看 `ended` 项目的分钟图、大户榜、追踪钱包和延迟。
- [x] `SignalHub` 页面新增快捷时间筛选：`24h / 72h / 7天 / 已关注`。
- [x] `SignalHub` 页面默认首屏只展示 12 条项目。
- [x] `SignalHub` 页面新增 `查看更多` 逐步展开更多 upcoming 项目。
- [x] 从常规 `Settings` 视图移除 `UI 心跳：Online`。
- [x] 修复 `Billing` 页面二维码顶部被裁切的问题。
- [x] 修复二维码弹窗中的图片裁切问题。
- [x] 将深色模式记录为后续独立主题迭代，不在本轮直接上线。

## Phase 30：认证防刷第一版

- [x] 注册接口按真实客户端 IP 增加双窗口限流：
  - `15` 分钟 `2` 次
  - `24` 小时 `5` 次
- [x] 重发验证邮件接口按真实客户端 IP 增加限流：
  - `1` 小时 `5` 次
- [x] 登录接口按真实客户端 IP 增加失败限流：
  - `15` 分钟 `10` 次
- [x] 真实客户端 IP 优先读取：
  - `X-Forwarded-For`
  - `X-Real-IP`
  - `request.remote`
- [x] 注册时拦截常见临时邮箱域名。
- [x] 临时邮箱错误返回可直接给普通用户阅读的提示文案。
- [x] 生产 HTTPS 域名下将 session cookie 切换为：
  - `Secure`
  - `HttpOnly`
  - `SameSite=Lax`
- [x] 前端继续复用现有 toast 展示限流和临时邮箱错误，不新增复杂人机验证 UI。

## Phase 31：深色模式独立主题

- [x] 新增全局主题上下文，支持 `light / dark` 双模式。
- [x] 主题选择写入本地存储，并在刷新后保留。
- [x] 首次进入时读取系统深浅色偏好。
- [x] 管理员 / 用户壳层顶栏增加主题切换按钮。
- [x] 登录 / 注册壳层增加主题切换按钮。
- [x] 扩展浅色 / 深色两套全局颜色 token。
- [x] 为 card / sheet / dialog / toast / table / input / button / badge / alert 适配深色模式。
- [x] 为登录注册页、主要壳层、项目详情区块和 `Billing` 主要区域适配深色模式。

## Phase 32：小交互收尾

- [x] `Projects` 搜索框增加清空入口。
- [x] `Projects` 搜索区显示当前命中结果摘要。
- [x] 管理员在 `Projects` 页可直接看到当前批量已选数量。
- [x] `Projects` 的 `已结束` 折叠状态写入本地存储。
- [x] 当搜索结果只命中历史项目且历史分组仍折叠时，给出一键展开提示。
- [x] `SignalHub` 搜索框增加清空入口。
- [x] `SignalHub` 页面增加筛选结果摘要（命中数 / 已关注 / 字段完整）。
- [x] `SignalHub` 页面增加统一的 `重置筛选` 操作。
- [x] `SignalHub` 预览抽屉中，已关注项目支持直接跳转到 `Projects` 对应条目。
- [x] `SignalHub` 空状态文案按筛选场景区分，而不是只显示同一条通用提示。
- [x] 管理员历史详情页标题直接带项目名。
- [x] 管理员历史详情页头展示项目状态与发射窗口。
- [x] 实时看板页头直接展示当前项目名与状态。

## Phase 33：Users 批量管理与管理员建号

- [x] 为 `users` 增加 `source` 字段，并扩展 `status` 到 `archived`。
- [x] `GET /api/admin/users` 支持按 `source` 筛选。
- [x] 新增 `POST /api/admin/users`，支持管理员直接创建用户。
- [x] 新增 `POST /api/admin/users/batch-status`，支持批量禁用 / 归档。
- [x] 新增 `POST /api/admin/users/batch-delete`，支持批量删除非管理员用户。
- [x] `Users` 页面增加多选框与“全选当前结果”。
- [x] `Users` 页面增加来源筛选。
- [x] `Users` 页面增加 `新建用户` 对话框。
- [x] `Users` 页面增加 `批量禁用 / 批量归档 / 批量删除` 操作。
- [x] `Users` 列表新增来源与邮箱验证状态展示。
- [x] 验证批量禁用后用户无法继续登录。
- [x] 验证批量归档后用户不再出现在默认活跃视图。
- [x] 验证批量删除后用户相关数据被清除，且管理员与当前登录账号不会被误删。

## Phase 34：备份 + 日志轮转 + 一键诊断

- [x] 新增运行时备份脚本，支持导出主库、总线库、SignalHub 库与关键配置。
- [x] 新增备份 systemd service + timer，默认每日执行并保留最近 7 天。
- [x] 新增运行时诊断脚本，支持一键打包服务状态、日志与数据库摘要。
- [x] 新增 logrotate 配置，覆盖 `events.jsonl` 与 `SignalHub-main/logs/*.log`。
- [x] 新增维护安装脚本，并接入生产安装脚本。
- [x] 更新服务器更新脚本，使其在拉代码后补装维护资产。
- [x] 在线上服务器实际执行一次备份脚本并确认产物生成。
- [x] 在线上服务器实际执行一次诊断脚本并确认诊断包生成。
- [x] 在线上服务器验证 `vwr-backup.timer` 已启用。
- [x] 在线上服务器验证 logrotate 配置可被系统接受。

## Phase 35：SR 排障案例与回放收口

- [x] 将 `SR` 问题按“RPC 能力 / 链上结构 / 解析规则”三层证据沉淀为正式文档。
- [x] 证明旧 `SR` 与新 `SR` 不是同一个链上对象。
- [x] 证明当前手动填写的 `SR` 内盘地址是有效的链上交互地址。
- [x] 证明当前生产 RPC plan 不满足历史日志 / trace 需求。
- [x] 证明新 `SR` 的链上买入结构与旧成功样本不同。
- [x] 证明原解析器会漏掉 `tax-only` 结构。
- [x] 使用更新后的解析器，对 `SR` 的 `447` 笔真实 tx hash 做全量重放。
- [x] 确认 `SR` 的 `events / minute_agg / leaderboard` 已经非零。
- [x] 将 `tax-only` fallback 作为正式生产规则提交到 GitHub 并同步服务器。
- [x] 2026-04-29 在服务器隔离库中重跑 `SR` 发射窗口，并确认最终 replay 与当前生产 baseline 完全对齐。
- [x] 沉淀 `SR` 重跑结论：自动 scan 可重建大部分数据，但仍需要正式化按 tx hash 强制 replay 缺口的运维工具。
- [x] 新增 `scripts/ops/replay_project_txs.py`，正式支持按项目 tx hash / 区块窗口重放。

## Phase 36：RPC 池化与自动降级

- [x] 为主项目 `backfill` 增加 `BACKFILL_HTTP_RPC_URLS` 多节点顺序配置。
- [x] 为主项目 `backfill` 增加 `BACKFILL_PUBLIC_HTTP_RPC_URLS` 公共 RPC 兜底配置。
- [x] 在主项目运行时维护每条回扫节点的能力状态：
  - `supports_basic_rpc`
  - `supports_historical_blocks`
  - `supports_logs`
  - `cooldown_until`
  - `last_error`
- [x] 实现 `RU quota exceeded` 长冷却。
- [x] 实现临时网络错误短冷却。
- [x] 让 `fetch_backfill_txhashes` 在日志扫描失败时自动切换下一条候选节点。
- [x] 让时间窗到区块的解析优先选择支持历史块查询的节点。
- [x] 在健康检查中暴露当前回扫池状态，便于线上排障。
- [x] 为 `SignalHub` 的 trace / 自动识别链路补同样的池化与能力检测。
- [x] 为 `SignalHub` 增加 `CHAINSTACK_BASE_HTTPS_URLS` 与 `CHAINSTACK_PUBLIC_HTTPS_URLS` 配置。
- [x] 在 `SignalHub /system/status` 中暴露 trace RPC 池状态。
- [x] 历史阶段曾将主项目公共回扫 RPC 顺序调整为 `mainnet.base.org -> publicnode -> llamarpc`；该结论已被 Phase 41 的 Ankr 主路径取代。
- [x] 历史阶段曾明确重放工具的 RPC 分工：logs 走快速公共节点，receipt 优先走 Chainstack 自有节点；该结论已被 Phase 41 的 Ankr 主路径取代。
- [x] 将历史 replay 的 block timestamp RPC 从 receipt RPC 中拆出，避免 Chainstack 当前 plan 的 archive 限制把单 tx 重放拖到 25 秒；当前默认主路径已切到 Ankr。
- [x] 为 `SignalHub` 增加 `CHAINSTACK_BASE_WSS_URLS` 多节点顺序配置。
- [x] 为 `SignalHub` 维护 WSS 节点运行状态：
  - `healthy`
  - `active`
  - `cooldown_until`
  - `last_error`
  - `last_connected_at`
  - `last_message_at`
- [x] 为 `SignalHub` 的 WSS 订阅实现连接失败自动切换。
- [x] 为 `SignalHub` 的 WSS 订阅实现限流 / 配额类错误冷却切换。
- [x] 在 `SignalHub /system/status` 中暴露当前活动 WSS 节点与 WSS 池状态。
- [x] 在线上验证 WSS 主节点故障后可自动切换到下一条候选节点。

## Phase 37：VOID 缺失记录排查与收口

- [x] 确认 `VOID` 当前项目基础信息完整：
  - `token_addr`
  - `internal_pool_addr`
  - `status`
  - `start_at / resolved_end_at`
- [x] 确认 `VOID` 当前主库聚合结果非零但明显偏少。
- [x] 确认 `VOID` 历史回扫任务存在批量失败。
- [x] 证明失败错误为公共节点要求 `eth_getLogs` 必须携带 `address` 过滤。
- [x] 定位当前日志扫描逻辑仍存在未带 `address` 的 `eth_getLogs` 请求。
- [x] 为日志扫描逻辑补齐 `address` 过滤，避免公共节点拒绝请求。
- [x] 重跑 `VOID` 时间窗口回扫，并重新核对 `events / minute_agg / leaderboard`。
- [x] 证明 `VOID` 剩余未入库候选 tx 为 `Tax Swapper / Allowance / Uniswap` 等非买入交易，而非新的买入漏判。
- [x] 证明 `VOID` 的部分 `Buy Function` 候选 tx 实际买到的是其他 `Virtuals` 项目代币，而不是 `VOID` 本身。

## Phase 38：回扫节点 RU 本地估算与后台可视化

- [x] 为主项目 `backfill` 节点池增加本地请求计数。
- [x] 为主项目 `backfill` 节点池增加 `estimated_ru` 本地近似估算。
- [x] 在健康检查中增加回扫节点池汇总使用信息。
- [x] 在健康检查中为每条回扫节点暴露：
  - `requestCount`
  - `estimatedRu`
  - `lastUsedAt`
  - `basicRequestCount`
  - `historicalBlockRequestCount`
  - `logsRequestCount`
- [x] 在 `Settings` 页面增加“回扫节点池”观测区块。
- [x] 在 `Settings` 页面明确标注“估算值不等于官方账单真值”。
- [x] 本轮不扩展到 `SignalHub trace` RU 估算。

## Phase 39：项目详情实时价格

- [x] 保留原有“买入市值（万 USD）”口径，不与实时价格混用。
- [x] 为项目详情新增当前内盘实时价格链。
- [x] 仅在已识别 `internal_pool_addr` 且池子支持 `getReserves()` 时启用。
- [x] 后端返回：
  - `tokenPriceV`
  - `tokenPriceUsd`
  - `liveFdvUsd`
- [x] 项目详情页增加：
  - `实时价格（USD）`
  - `实时价格（V）`
  - `实时 FDV（万 USD）`
- [x] 第一阶段不做历史时点价格，只使用当前 `VIRTUAL/USD` 价格服务。
- [x] 对 `token0/token1` 不可读、但 `getReserves()` 可读的非标准内盘池增加 fallback 判定。
- [x] 对只返回两段储备值的非标准 `getReserves()` 响应增加兼容，避免 `VOID` 这类池子直接显示为空。

## Phase 40：项目详情实时价格异步加载

- [x] 将项目详情主接口中的实时价格计算拆出，避免首屏被链上读取阻塞。
- [x] 新增管理员与用户的独立 project market 接口。
- [x] 为单项目实时价格增加短 TTL 缓存，减少重复读取池子与 decimals。
- [x] 前端改为先加载主详情，再异步补 `实时价格 / 实时 FDV`。
- [x] 历史项目详情继续允许显示“当前实时价格”，不因 `ended` 状态隐藏。

## Phase 41：项目完整性验收与回扫执行优化

- [x] 新增 `scripts/ops/audit_project_window.py`，把项目窗口结束后的完整性验收固化为可执行工具。
- [x] 审计工具支持按项目窗口重新发现候选 tx，并对照 `events / scanned_backfill_txs / dead_letters` 输出 `green / red / observed` 状态。
- [x] 审计工具支持输出 replay 修复命令，并可写出缺口 tx 文件。
- [x] 将后台手动 scan range 的 tx 处理从逐笔执行改为按 `RECEIPT_WORKERS*` 配置并发执行。
- [x] 将 Ankr 充值后的当前 RPC 推荐写入 benchmark 文档顶部，旧 Chainstack / mainnet.base.org 结论标注为历史记录。
- [x] 在 SR replay 文档中补充完整性审计工具和当前 Ankr 主路径。
- [x] 在线上删除 `SR` 派生数据后，用生产 scan job 完整重建，并通过 `green` 审计确认无需 repair replay。
- [x] 2026-04-30 生产部署后复跑 `SR` 完整性审计，结果仍为 `green`，无需 repair replay。
- [ ] 将项目完整性审计接入后台 Admin UI，形成项目结束后的可视化验收结果。
- [ ] 将公网 `/health` 与管理员 diagnostics 彻底拆分，避免后续新增运行态字段时再次扩大暴露面。

## Phase 42：目标代币价格实时化

- [x] 明确价格语义：`scheduled / prelaunch` 显示“开盘参考价”，只有 `live` 打新中显示“实时价格”。
- [x] `live` 项目 market 接口缓存 TTL 降到 `0.25s`，前端按 `250ms` 轮询。
- [x] `scheduled / prelaunch / ended` 保持低频轮询，避免发射前无意义高频读链。
- [x] 对 `eth_call` 的 `execution reverted` 做确定性失败处理，不再按 RPC transient error 指数退避重试。
- [x] 为目标代币内盘缓存 `token0/token1` 或 fallback 布局，以及 token decimals，避免每次价格刷新重复探测。
- [x] market 接口返回 `priceUpdatedAt / priceBlockNumber / priceLatencyMs / marketPriceMode / recommendedRefreshMs`。
- [x] 前端价格卡片显示更新时间、区块号和读取耗时，避免把发射前参考价误认为成交后的实时价格。
- [x] writer 在 `prelaunch / live` 阶段预热 market snapshot，提前缓存池子布局和 decimals。
- [ ] 线上观察一次真实 `live` 发射窗口，确认 250ms 轮询不会触发 Ankr 限速。

## Phase 43：Virtuals 税率与含税估算 FDV

- [x] 通过 Virtuals API 读取 `signalhub_project_id` 对应的公开 launch 信息。
- [x] 按 `BONDING_V5 + antiSniperTaxType` 计算反狙击税衰减，并叠加基准税率。
- [x] 后端 market 接口返回 `buyTaxRate / taxStartAt / taxEndAt / estimatedFdvUsdWithTax / estimatedFdvWanUsdWithTax`。
- [x] 前端把“含税估算 FDV”单独拎成 KPI 卡片；`scheduled / prelaunch` 可用于发射前估值判断，`live` 可用于打新中实时判断。
- [x] 含税估算 FDV 卡片增加微弱灯光，并在跨过 `10 万 USD` 档位时闪耀：上破用主题色，下破用红色。
- [x] 保留本地 `taxFdvSim=up/down` 回放入口，仅 `localhost / 127.0.0.1` 生效，方便复测灯光且不污染真实数据。
- [x] 本地用 ISC `72752` 验证 Virtuals API 字段和历史税率：`27% -> 26% -> 25% -> 24%`。
- [x] 2026-04-30 已直接同步到阿里云轻量应用服务器生产环境，部署 commit `44047aa`，生产健康检查通过。
- [x] 项目详情展示口径调整：累计税收明确为 `V`，前端隐藏 `代币价格（V）`，`当前 FDV（不含税）` 并入 USD 价格卡，`含税估算 FDV` 与税率保持独立卡片并保留灯光。
- [x] 发射阶段 `含税估算 FDV` 与 `代币价格` 共用 market 刷新节奏，前端 live 轮询提升到 `250ms`。
- [x] market 接口新增链上观察税率证据：最新买入事件按 `tax_v / spent_v_est` 反推税率；新鲜且偏离官网预测 `3` 个百分点以上时覆盖 `buyTaxRate`，保护含税 FDV 与成本位比较。
- [x] 前端 Tax Rate 区域展示证据状态：官网预测、链上确认、链上覆盖或链上观察过期。
- [x] 对未知/缺失的 `BONDING_V5 antiSniperTaxType` 增加保护：后端返回 `taxConfigKnown=false`，前端显示 `Tax Rate ?` 与风险提示，不再把未知配置默认为 `98m`。
- [ ] 部署到生产后，在下一次真实 `live` 发射窗口观察税率徽标与含税 FDV 是否和 Virtuals 页面一致。

## Phase 44：打新过程大户成本位指标

- [x] 前端标签统一为 `当前 FDV（不含税）` 与 `含税估算 FDV`，不再使用容易歧义的“有效市值”。
- [x] 后端 overview 榜单补充 `breakevenFdvV`，让前端能用 V-native 成本和当前含税估算 FDV 做同口径比较。
- [x] 项目详情新增 `榜单 V / 榜单成本 / 成本位 / V 成本位`，其中 `榜单成本 / 成本位 / V 成本位` 都带 `ⓘ` hover 解释。
- [x] 成本位比较规则固定为严格小于：仅当大户成本 FDV `< 当前含税估算 FDV` 时计入低于当前估值。
- [x] 大户榜单保留原始数据，但成本位计算默认排除疑似团队买入；命中地址在榜单中显示 `疑似团队` 标记。
- [x] `live` 阶段 overview 聚合按 `250ms` 轮询，打新成本位跟随大户榜单入库和含税 FDV 一起刷新。
- [x] 本地构建并重启 writer 验证，不影响当前云端生产服务。

## Phase 45：SignalHub 身份防错与发射模式识别

- [x] 线上 TDS 从已拒绝的 Virtuals 项目 `72336` 修正为当前有效项目 `72562`，主库已保留修正前备份。
- [x] `SignalHub-main` upcoming feed 排除 `REJECTED / CANCELED / ARCHIVED / INACTIVE` 等终态项目，避免旧项目仅因未来 `launch_time` 继续混入候选列表。
- [x] 主项目消费 SignalHub 时优先按 `signalhub_project_id` 精确匹配；同名兜底只允许用于尚未绑定 SignalHub ID 的手工项目。
- [x] 前端 SignalHub 页面同步收紧同名兜底，避免同名旧项目把新项目误判为已关注。
- [x] market 接口返回 `launchMode / launchModeLabel / isRobotics / isProject60days / virtualsStatus` 等字段；项目详情在含税估算 FDV 卡片展示 `Robotic Launch / Unicorn Launch` 徽标。
- [x] 修正 TDS 税率窗口误判：`BONDING_V5 + antiSniperTaxType=1` 必须按 `60s` 秒级衰减处理，即使 `isProject60days=true`；`antiSniperTaxType=2` 才按 `98m` 分钟级衰减处理。
- [x] 将大户榜单 `成本 FDV` 文案修正为 `含税成本 FDV`，明确它是用实际总支出 V / 扣税后到手 token 反推的回本 FDV，不是当前市值。
- [x] SignalHub `/bot/feed/upcoming` 透出 `launchInfo / antiSniperTaxType / isProject60days / isRobotics / launchMode` 等官网原始税率配置，主项目归一化消费这些字段；SignalHub 页面展示 Launch Type 与 Anti-sniper 标签。
- [ ] 下一次真实发射前，在 SignalHub 页面确认同名项目不会被错误复用；如 Virtuals API 已返回 `REJECTED`，候选列表应不再显示该项目。

## Phase 46：ISC 原生发射回放测试

- [x] 新增 `scripts/ops/native_launch_replay.py`，用于本地/服务器临时库原生回放发射窗口。
- [x] replay 默认优先使用 `ANKR_BASE_HTTP_RPC_URL`，避免误走 Chainstack 非 archive 套餐。
- [x] 2026-04-30 在服务器用 ANKR 跑完 ISC 前 `10` 分钟 `5x` replay：`89` 笔 tx、`74` 条事件、`115` 个采样点。
- [x] 验证 `含税估算 FDV` 公式误差为 `0`，历史 `eth_call(getReserves)` 没有降级。
- [x] 验证 `打新成本位` 会随原生事件入库变化，并默认排除 ISC 榜一疑似团队低成本买入。
- [x] 结果记录见 `docs/ISC-native-replay-test-2026-04-30.md`。

## Phase 47：生产同步安全加固

- [x] 新增 `scripts/ops/deploy_production_safe.sh`：生产同步只走白名单文件，默认 `--dry-run`，显式 `--apply` 才会推送。
- [x] 部署脚本排除 `.venv / node_modules / data / secrets / config.json / SignalHub-main/.env / SignalHub-main/signalhub.db`，并使用 `--no-owner --no-group`，避免把 macOS 属主同步到 Linux。
- [x] 文档记录误同步恢复顺序：停服务、备份现场、恢复服务器 DB 备份、删 WAL/SHM、重建 venv、恢复生产 config、修复属主、重启健康检查。
- [x] 2026-05-01 生产已部署 commit `2995c95`，健康检查通过；主程序 backfill RPC 顺序确认为 `Ankr -> Alchemy -> Base public -> PublicNode`。
- [x] 2026-05-01 为 `vwr-signalhub.service` 增加 `/etc/virtuals-whale-radar/signalhub-rpc.env` drop-in，SignalHub HTTPS 识别链路同样走 Ankr 优先。
- [x] runtime backup 排除应用目录下的 SSL 私钥目录，不通过放宽私钥权限来修备份失败；已手动执行 `vwr-backup.service` 并确认成功。

## Phase 48：生产最终验收记录（2026-05-01）

- [x] 线上 `/opt/virtuals-whale-radar/DEPLOYED_COMMIT` 已跟随文档同步更新；最终 live commit 以后续同步完成后的 `DEPLOYED_COMMIT` 为准。
- [x] 生产健康检查通过：`SignalHub /healthz = 200`，主程序 `/health ok=true`，`runtimePaused=false`，`writer / realtime / backfill / SignalHub` 均为 running。
- [x] 生产 `backfillRpcPool` 验证为 `rpc.ankr.com -> base-mainnet.g.alchemy.com -> mainnet.base.org -> base-rpc.publicnode.com`。
- [x] 线上 `https://virtuals.club/admin/projects/12?project=ISC` 返回 `HTTP/2 200`，加载本次前端构建 `index-DC4selLQ.js`。
- [x] ISC 生产 market 接口已返回关键字段：`Robotic Launch`、`antiSniperTaxType=2`、`taxConfigKnown=true`、`taxConfigStatus=bonding_v5_98m`、`estimatedFdvWanUsdWithTax`、`taxEvidenceStatus=chain_stale`。
- [x] ISC 生产 overview 接口已返回打新成本位所需结构：`whaleBoard=20`、`trackedWallets=5`、`minutes=75`，且榜单项包含 `breakevenFdvUsd / breakevenFdvV / isTeamCandidate / costExcluded`。
- [ ] 下次发版前补一个可复用的 authenticated frontend smoke test，自动检查登录后页面 console error、关键指标文案和 replay 控制开关。

## Phase 49：生产 RPC 切回 Chainstack 优先（2026-05-07）

- [x] 使用 Chainstack Platform API 找到当前 Base mainnet running 节点，并用 auth key 构造 HTTPS/WSS endpoint；不把 endpoint token 写入 Git 或文档。
- [x] 服务器侧验证 Chainstack HTTPS `eth_blockNumber` 与 WSS `eth_blockNumber` 均可用。
- [x] 生产 `/etc/virtuals-whale-radar/rpc.env` 新增 `CHAINSTACK_BASE_HTTP_RPC_URL / CHAINSTACK_BASE_WS_RPC_URL`，并保留 Ankr / Alchemy 作为后备。
- [x] 生产主程序 `config.json` 切换为 Chainstack-first：`Chainstack -> Ankr -> Alchemy -> Base public -> PublicNode`。
- [x] 生产 SignalHub drop-in `/etc/virtuals-whale-radar/signalhub-rpc.env` 切换为 Chainstack-first HTTPS/WSS。
- [x] 重启 `vwr-signalhub / writer / realtime / backfill` 后健康检查通过：`/healthz=200`、`/health ok=true`、`runtimePaused=false`、`ws_connected=true`。
- [x] 更新 `config.example.json`，后续部署默认按 Chainstack-first 占位配置。
- [x] 2026-05-07 在服务器隔离库中用 Chainstack 跑完 ISC 前 `10` 分钟 `5x` 原生 replay：`89` 笔 tx、`74` 条事件、`112` 个采样点，`logErrors=[]`，historical `eth_call` 支持正常。
- [x] 同一当前代码用 ANKR 复跑对照：`89` 笔 tx、`74` 条事件、`116` 个采样点；V-native 口径下 Chainstack 与 ANKR 的最终 `tokenPriceV / 含税 FDV / 榜单成本` 基本一致，USD 差异来自 replay 启动时的当前 `VIRTUAL/USD` 折算价。
- [x] 结果记录见 `docs/ISC-chainstack-native-replay-test-2026-05-07.md`。
- [ ] 下一次真实发射窗口观察 Chainstack-first 在完整 logs / receipt / historical block 路径下的稳定性；若触发 plan 限制，自动回退 Ankr。

## Phase 50：Chainstack-only 测试流程整合

- [x] 整理当前已有测试入口：前端构建/lint、生产健康检查、Chainstack RPC smoke、原生 replay、前端可视化 replay、窗口完整性审计、缺口 tx 修复、安全同步 dry-run。
- [x] 新增 `docs/chainstack-test-runbook.md`，把当前测试能力整合成 Chainstack-only 的可复用执行顺序。
- [x] 2026-05-07 按 runbook Step 1/2 复测：Chainstack HTTP `eth_blockNumber`、historical block、50 blocks logs、recent receipt、WSS `eth_blockNumber` 均通过；生产四个核心服务 active，`/health ok=true`。
- [x] 新增 `scripts/ops/run_chainstack_test_suite.py`，把 Chainstack env check、RPC smoke、生产健康检查、隔离 replay、项目窗口审计整合为一个只读 JSON 报告入口。
- [x] 2026-05-07 在服务器执行完整 orchestrator：`smoke + health + ISC 10m replay + ISC audit`，结果 `green`，报告路径 `data/audits/chainstack-suite-20260507-full.json`。
- [x] orchestrator 结果摘要：RPC smoke 全通过；生产四服务 active；replay `89 tx / 74 parsed / 74 inserted / 113 samples`；ISC audit `candidateTxCount=602`、`repairCandidateTxCount=0`、`unresolvedDeadLetterCandidateTxCount=0`。
- [x] 2026-05-07 按 Chainstack-only 顺序执行 TDS 完整窗口 replay：`504 tx / 128 parsed / 128 inserted / 144 samples`，historical `eth_call` 支持正常，`logErrors=[]`，最终 `costPosition=5/20`。
- [x] 2026-05-07 按 Chainstack-only 顺序执行 SR 完整窗口 replay：`753 tx / 602 parsed / 602 inserted / 144 samples`，historical `eth_call` 支持正常，`logErrors=[]`，最终 `costPosition=18/19`。
- [x] 2026-05-07 执行 Chainstack 故障注入：missing env 与 bad HTTP/WSS endpoint 均按预期 `status=red`；测试只使用临时环境变量，不改线上配置。
- [x] 修复 `run_chainstack_test_suite.py` 的 missing env 报告：HTTP 与 WSS 同时缺失时不再只显示最后一个缺失项。
- [x] 新增 `docs/chainstack-full-window-test-2026-05-07.md` 记录 TDS/SR 完整窗口、故障注入与测试后生产健康结果。
- [x] 同步到服务器后复验故障注入修复：`chainstack-suite-20260507-fault-missing-env-fixed.json` 同时列出 HTTP/WSS 缺失，`chainstack-suite-20260507-fault-bad-rpc-after-sync.json` 按预期 `red`。

## Phase 51：98 分钟税率项目自动买入策略离线回测

- [x] 新增 `scripts/ops/backtest_launch_strategy.py`，从 replay `samples.jsonl` 只读回测发射窗口买入策略；不接真实交易，不写生产 DB。
- [x] 在服务器用 SR 144-sample 完整窗口跑基础参数网格：`17,496` 个策略组合，`2,592` 个组合触发。
- [x] 在服务器用 SR aggressive 参数网格测试允许 FDV 高于榜单成本的变体：绝对收益可提升，但资金效率明显下降。
- [x] 用 TDS 完整窗口做非目标模式对照：在 `50,000 V+` 门槛下 `0` 触发。
- [x] 用 ISC 早段 replay 做低门槛压力测试：`10,000 V / 20,000 V / 30,000 V / 40,000 V` 可触发，但早段 mark-to-market 强负；支持默认不把门槛降太低。
- [x] 重新跑 SR 高采样完整窗口 replay：`753 tx / 602 parsed / 602 inserted / 1,034 samples`，`logErrors=[]`。
- [x] 用 SR 高采样样本复测：用户基线策略 `boardSpentV>=100,000 / tax<=92 / FDV<=榜单成本 / 50V / 60s cooldown / 2 buys in 120s -> 600s` 触发 `2` 次，投入 `100V`，最终约 `+38.05V`。
- [x] 记录离线回测结果到 `docs/launch-strategy-backtest-2026-05-07.md`。
- [x] 补做 SR 专项梯度与场景压力测试：新增 `scripts/ops/sr_strategy_scenario_suite.py`，覆盖单参数梯度、二维组合梯度、延迟/采样/滑点/榜单偏差/税率偏差、500 次蒙特卡洛扰动和 9 类合成数据形态。
- [x] 记录补测结果到 `docs/sr-strategy-scenario-suite-2026-05-07.md`；结论更新为：SR 单样本上 `50,000 V` 激进入场收益更高，但仍不能直接上线真实交易，必须先做 realtime dry-run signal emitter。
- [x] 按控制变量/取消变量口径补跑 SR 消融测试：新增 `scripts/ops/sr_strategy_ablation_suite.py`，覆盖 `70k/80k/90k`、不限制榜单 V 只看税率 `95-90`、保留/取消 FDV 成本条件、取消单个变量、多变量组合。
- [x] 记录消融结果到 `docs/sr-strategy-ablation-suite-2026-05-07.md`；关键发现：`70k/80k/90k + tax<=95 + fdv` 在 SR 上首买都落在 `98,430 V / tax 93`，收益约 `+42.11%`；`tax_only` 与 `tax+fdv` 是完全不同风险口径。

## Phase 52：策略测试矩阵与文档分层

- [x] 新增用户维护的需求纲领：`docs/requirements-outline.md`。
- [x] 新增 Plan 纲领：`docs/plan-index.md`。
- [x] 新增 Todo 纲领：`docs/todo-index.md`。
- [x] 新增 Phase 052 子 plan：`docs/phases/phase-052-strategy-test-matrix-plan.md`。
- [x] 新增 Phase 052 子 todo：`docs/phases/phase-052-strategy-test-matrix-todo.md`。
- [x] 用户确认 Phase 052 默认测试目标和风险边界后，开始实现统一测试 runner。
- [x] 新增 `scripts/ops/strategy_test_matrix_runner.py`，统一覆盖控制变量、取消变量、多变量组合、数据形态模拟、税率异常、RPC/数据延迟和执行层模拟。
- [x] 在服务器使用 Chainstack replay 样本跑完 SR 高采样、SR 144-sample、ISC 10 分钟和 TDS 完整窗口矩阵。
- [x] 输出统一报告：
  - Markdown：`docs/phases/phase-052-strategy-test-matrix-report.md`
  - JSON：`data/backtests/strategy-test-matrix-20260507.json`
- [x] 报告规模：`737` 条规则、`34` 类场景、`4,136` 个结果。
- [x] 报告明确把 `tax-only / no-FDV-cost / no-board-spent / low-sample first-buy` 归入对照或拒绝项，不作为直接交易候选。
- [x] 2026-05-10 修正 SR 结果口径：旧 `14` 个候选拆解为 `7` 条规则、`3` 个主样本实际入场簇。
- [x] 2026-05-10 明确新事件模型：`pool_state_change + tax_tick + heartbeat`，其中 `pool_state_change` 覆盖 buy、sell、unknown pool event。
- [x] 2026-05-10 明确税率变化瞬间必须记录为 `tax_tick`，即使没有交易。
- [x] 2026-05-10 明确收益评估只看 tax 降到 `1%` 的 end 表现，不再默认计算 `1m / 3m / 5m / 10m`。
- [x] 新增本地 SR-only 结果级重筛脚本：`scripts/ops/sr_strategy_recalc_from_matrix.py`。
- [x] 2026-05-10 定位 RPC 根因：本地 `BACKFILL_*` 优先指向旧 endpoint，导致历史 block/logs 返回 403；有效 Chainstack endpoint 已在 `HTTP_RPC_URL`。
- [x] 2026-05-10 修复本地 `config.json` backfill 顺序：`BACKFILL_HTTP_RPC_URL` / `BACKFILL_HTTP_RPC_URLS` 改为有效 Chainstack endpoint。
- [x] 2026-05-10 修复本地 `SignalHub-main/.env` Chainstack HTTPS/WSS 顺序：SignalHub 本地运行优先使用有效 Chainstack endpoint。
- [x] 新增真正事件级 SR replay 脚本：`scripts/ops/sr_event_level_replay.py`。
- [x] 用 Chainstack 完成 SR event-level replay：`751` tx / `601` buy / `24` sell / `126` unknown pool event / `99` tax tick / `1089` samples。
- [x] 输出事件级报告：`docs/phases/phase-052-sr-event-level-replay-2026-05-10.md`。
- [x] 验证买入次数：`1089` 样本中仅 `25` 个满足硬条件且全部集中在一个短信号簇；当前 `60s + burst2 -> 10min` 执行限制将其压缩为 `2` 次买入。
- [x] 修正 SR 策略门槛：榜单累计投入门槛降为 `5,000 V`，执行限制改为“同一税率档位最多买一次”，并用现有 event-level 样本重算。
- [x] 新口径结果：`gate_5k_tax95_fdv_one_per_tax` 买入 `6` 次，投入 `300 V`，end 收益约 `+62.9736%`。
- [x] 只读检查生产服务器 RPC：主程序实际 backfill 顺序为 `Chainstack -> Ankr -> Alchemy -> mainnet.base.org`，SignalHub HTTPS 顺序为 `Chainstack -> Ankr -> Alchemy`，WSS 为 Chainstack。
- [x] 生产 Chainstack smoke 通过：`eth_blockNumber / SR historical block / SR 50 blocks logs` 均成功，约 `75-107ms`。
- [x] 生产健康检查通过：四个服务 active，`/healthz ok`，`/health ok=true`，`runtimePaused=false`。
- [x] 用最新策略完成 ISC 完整 event-level replay：`600 tx / 322 buy / 41 sell / 237 unknown / 99 tax_tick / 1576 samples`。
- [x] ISC `300 V` 上限结果：最佳 `tax<=89`，买入 `6` 次，投入 `300 V`，end 收益约 `+38.1828%`。
- [x] ISC 不限制总投入结果：最佳收益率仍为 `tax<=89`，买入 `28` 次，投入 `1400 V`，end 收益约 `+38.7567%`。
- [x] 否掉“看到榜单 V 暴增 / FDV 反弹后再加仓”的后验确认策略，避免把 SR 已重新定价后的信号当成前置信号。
- [x] 新增动态买入重算脚本：`scripts/ops/recalc_dynamic_buy_strategy.py`。
- [x] 确认当前采用策略：`25V` 基础买入，若当前含税 FDV 低于我方历史加权买入 FDV `20%` 以上则买 `50V`；某税率分钟买入后，下一税率分钟 FDV 相对上一买点变化 `<=10%` 则暂停一个税率档。
- [x] 用 SR/ISC 事件级样本完成 after1 动态策略重算，并输出 `data/backtests/dynamic-buy-recalc-after1-flat10-20260510.json`。
- [x] 输出最终策略整理文档：`docs/phases/phase-052-final-dynamic-buy-strategy-2026-05-10.md`。
- [x] SR `tax<=95` 主规则结果：买入 `5` 次，投入 `125 V`，end 收益约 `+86.133020 V / +68.9064%`。
- [x] ISC ROI 最优 `tax<=89`：买入 `14` 次，投入 `350 V`，end 收益约 `+136.284025 V / +38.9383%`。
- [x] Phase 052 策略冻结，后续交易执行链路转入 Phase 053。

## Phase 53：发射策略执行链路

- [x] 新增 Phase 053 子 plan：`docs/phases/phase-053-launch-execution-pipeline-plan.md`。
- [x] 新增 Phase 053 子 todo：`docs/phases/phase-053-launch-execution-pipeline-todo.md`。
- [x] 新增执行链路脚本骨架：`scripts/ops/launch_execution_pipeline.py`。
- [x] 新增本地 smoke test：`scripts/ops/test_launch_execution_pipeline.py`。
- [x] 实现 after1 `StrategyEvaluator -> BuyIntent`。
- [x] SR dry-run 输出：`data/backtests/launch-execution-dry-run-sr-tax95-after1-20260510.json`，`5` 个 BuyIntent，`2` 个暂停，`tradeSent=false`。
- [x] ISC dry-run 输出：`data/backtests/launch-execution-dry-run-isc-tax89-after1-20260510.json`，`14` 个 BuyIntent，`14` 个暂停，`tradeSent=false`。
- [x] `SafeBroadcaster` 默认拒绝广播。
- [x] 收集 Virtuals 成功买入交易样本：SR/ISC 共 `19` 个样本。
- [x] 完成 OrderBuilder calldata parity test：direct route `18` 个样本核心字段一致。
- [x] 输出 calldata 研究报告：`docs/phases/phase-053-virtuals-buy-calldata-research-2026-05-10.md`。
- [x] 实现标准 4 参数 calldata encoder 和显式参数 unsigned buy tx builder。
- [x] 确认 spender/allowance 需求：实际 spender 是 `0x02fe8ec3d9bbf7318eb54590bcc39198a8b47ded`，不是 direct router。
- [x] 输出 spender trace 报告：`docs/phases/phase-053-virtuals-buy-spender-trace-2026-05-10.md`。
- [x] 实现 TxSimulator：`eth_call / allowance / balance / gas / nonce / deadline`。
- [x] 新增只读 probe：`scripts/ops/tx_simulator_probe.py`。
- [x] `tx_simulator_probe.py` 优先使用独立 `VWR_EXEC_HTTP_RPC_URL`，并输出 `rpcSharedWithMain`。
- [x] 新增发射前 readiness 检查脚本：`scripts/ops/launch_readiness_check.py`，默认只读验证 `25V / 50V` 两档买入模拟。
- [x] 新增统一 execution RPC helper：`scripts/ops/execution_rpc.py`；readiness、dry-run、prewarm executor、latency probe、local signer probe 均复用同一入口。
- [x] 新增只读 RPC 压力观察脚本：`scripts/ops/launch_rpc_pressure_probe.py`，同一报告记录主采集 RPC、backfill RPC、execution RPC、项目 market reserve latency。
- [x] 本地 `TDS` 小样本 RPC 压力 probe 已按生产同构入口复测：`.env.local` 提供 `VWR_EXEC_HTTP_RPC_URL`，`execution_rpc.py` 自动读取该 ignored 文件，输出 `data/backtests/launch-rpc-pressure-probe-local-autoenv-20260511T064241Z.json`，`executionRpcSharedWithMain=false`。
- [x] 本地 `.env.local` 当前复用生产 execution endpoint；口径是“本地同构测试 -> 通过后同步生产”的单活流程，减少配置漂移，本地测试和远端生产不要并行跑同一套交易 RPC。
- [x] 只有在需要本地长期并行压测或多人同时开发时，才改为单独 dev/local Chainstack endpoint。
- [x] `execution_rpc.py` 已加本地广播保护：如果 execution RPC 来自本地 `.env.local`，真实广播默认阻断；只有显式设置 `VWR_ALLOW_PROJECT_ENV_BROADCAST=1` 才允许本地 canary 广播。
- [x] 完成买入方式通用性审计：`docs/phases/phase-053-virtuals-buy-route-universality-audit-2026-05-10.md`。
- [x] 第一版自动买入只支持 direct buy route，排除 team/initialization 和 alternate/aggregator route。
- [x] 将 `BuyIntent` 绑定到 token、slippage、deadline。
- [x] 接入 slippage 口径，禁止长期 `amountOutMin=0`。
- [x] 输出 order binding / `amountOutMin` 报告：`docs/phases/phase-053-virtuals-order-binding-minout-2026-05-10.md`。
- [x] TDS 真实只读 probe：非零 `amountOutMin` 可生成，余额不足时 simulation 阻断，`tradeSent=false`。
- [x] 实现 LocalSigner 并完成本地签名但不广播 smoke test：`docs/phases/phase-053-local-signer-no-broadcast-2026-05-10.md`。
- [x] 并发化执行链路只读检查，降低冷路径模拟延迟。
- [x] 新增延迟探针：`scripts/ops/launch_latency_probe.py`。
- [x] Chainstack RRR no-broadcast 延迟探针：中位 `coldPrepareMs=1278.3ms`，`hotPathLocalMs=12.8ms`，输出 `data/backtests/launch-latency-probe-chainstack-rrr-20260510.json`。
- [x] `buy_virtual_canary.py` 增加 `sendRawMs / totalToSendAckMs / waitReceiptMs`，明确第一买入考核 `send ACK`，不再用 receipt 时间衡量提交速度。
- [x] 使用真实 burner 钱包做 no-broadcast 演练，签名后不广播，`tradeSent=false`。
- [x] 极小额主网 canary 记录真实 `eth_sendRawTransaction` ACK 延迟：冷路径 `sendRawMs=438.6ms`、`totalToSendAckMs=2644.1ms`；热路径 `triggerToSendAckMs=450.6ms`。
- [x] 真实 canary receipt 均成功，实际花费合计 `0.002 VIRTUAL` 买入 RRR。
- [x] 新增 `scripts/ops/prewarmed_buy_canary.py`，沉淀 hot-path canary 工具，默认不广播。
- [x] `prewarmed_buy_canary.py` dry-run 验证 allowance 不足时正确阻断，`tradeSent=false`。
- [x] 修复 `approve_virtual_spender.py` 授权后 allowance stale 读数：receipt 后轮询确认。
- [x] `approve_virtual_spender.py` 和 `approve_erc20_spender.py` 优先使用独立 execution RPC；支持 `--skip-sign` 只读验证 approve 可行性；明确授权不要求当前 VIRTUAL 余额足够，只要求 Base ETH gas。
- [x] 真实授权广播默认要求独立 execution RPC；共享主采集 RPC 时 fail-closed，除非显式 `--allow-shared-rpc-broadcast`。
- [x] 2026-05-11 完成 ROO 25V VIRTUAL 授权广播，tx `0x2b5573753c5863f17fc784043956ecafdae04f9adc77a7bd7639226da15d5833`，allowance 已确认到 `25 VIRTUAL`；这只是授权，不是 ROO 买入。
- [x] 2026-05-11 完成 ROO 300V VIRTUAL 精确授权广播，tx `0xd7ea8c4ec30601edc67f8579a334abaecab0e38970608c79fbd8e6cc5096b36e`，allowance 已确认到 `300 VIRTUAL`；授权不要求当前 VIRTUAL 余额足够。
- [x] ROO 300V 授权后 readiness 复查：25V 只剩项目未 live 的 `ethCall/estimateGas`；50V 不再报 allowance，只剩 balance 与项目未 live。
- [x] 授权后 ROO 25V readiness：balance/allowance 已通过；项目仍为 `scheduled`，`buy()` 的 `eth_call / estimateGas` 仍 revert，当前尚未达到可买状态。
- [x] 新增 `scripts/ops/approve_erc20_spender.py` 和 `scripts/ops/sell_virtuals_token.py`，支持 canary token 精确授权后卖回 VIRTUAL。
- [x] `sell_virtuals_token.py` 优先使用独立 execution RPC；真实卖出广播默认要求独立 execution RPC。
- [x] 已将本轮 canary 买入的 TDS / RRR / AURA / ASDSDA 全部卖回 VIRTUAL；卖回合计 `3.9223602 VIRTUAL`，最终 burner VIRTUAL 余额 `12.587713615542899411`。
- [x] 2026-05-18 用已结束但仍有内盘的 `TDS` 做真实生产 canary：`0.1 VIRTUAL` 买入成功，exact TDS 授权成功，exact amount 卖回成功，三笔 receipt 均为 `0x1`。
- [x] 2026-05-18 12:23 CST 复测 TDS 小额真实买卖：预检通过；买入 tx `0x98ff0ba6a5a99b006242a1bb0319cc8738389bf856f4713f211a6b5c63212375`、exact 授权 tx `0xb1889f8825294eb0b7ba14b8817cc464c172aabd387e156e28e1e758363e5677`、卖回 tx `0x161ba3dbaec8bbbf0b5787f41e8a9b217be1fe1a36c1afe4456021e59b367894`，三笔 receipt 均 `0x1`；收尾 TDS 余额 `0`、TDS sell allowance `0`、active fuse `0`。
- [x] 修复 `sell_virtuals_token.py` 在 sell quote 构造时缺失 `effective_slippage_bps / buy_tax_rate_pct / tax_adjusted_amount_out_raw` 的崩溃；新增无网络单测覆盖 sell binder 的 `PoolQuote` 结构。
- [x] TDS canary 收尾核对：TDS 余额 `0`、TDS sell allowance `0`、active fuse `0`、`/health` 与 SignalHub `/healthz` 均正常。
- [x] 新增 `scripts/ops/full_window_auto_trigger_canary.py`，用于验证“live 窗口数据流自动触发买入/卖出”，不再把手动 buy/sell canary 当作自动触发验证。
- [x] 2026-05-18 12:42 CST 完成 TDS 全窗口自动触发链路 canary：99 tick 人工 fixture 样本流自动触发 fixture tax `95%` 买入 `0.01 VIRTUAL`，tx `0x95dd79671943b3a700beba94073fd0089eef404c5ab42d3a8fac685dcc345bb4`，receipt `0x1`；后续 fixture 样本在 tax `92%` 强制触发卖出，tx `0x45f81a89de82f9e283856127fcbe329d2fea5ec302a4e561b9f5632015767130`，receipt `0x1`；summary `ok=true`、`tdsBalanceRawAfter=0`、`post_sell_balance_zero=1`。该测试只证明自动触发链路，不代表真实项目税率走势或生产卖出税率策略。
- [x] 修复全窗口自动触发 canary 的 receipt 后余额 stale 问题：买入后等待 token balance 可见，卖出后等待 token balance 归零，再写 summary。
- [x] 修复全窗口自动触发 canary 的账本污染问题：卖出评估只读取本次 run 的 buy/sell strategy 记录，避免 TDS 历史 canary 记录影响 position 口径。
- [x] `full_window_auto_trigger_canary.py` 默认卖出税率上限改回 `30%`；高税率强制卖出 canary 必须显式传 `--force-high-tax-sell-canary`。
- [x] 新增 `scripts/ops/historical_live_auto_trigger_canary.py`，用真实历史 SR 样本流驱动当前 TDS internal-market 小额真实买卖，验证自动触发、前端/DB 运行时改参热加载和生产执行器广播链路。
- [x] 2026-05-18 14:33 CST 完成历史样本驱动真实 canary：SR `1089` 个样本；sample `30` 买入改参后 `strategy_config_reloaded=1`；sample `55` / tax `95%` 自动买入 `0.01 VIRTUAL`，tx `0x541481388328fb7a8181b05ed749518c0fffc605b05badada5b5a8db584062e5`，receipt `0x1`；sample `700` 卖出改参后 `sell_config_reloaded=1`；sample `819` / tax `30%` 自动卖出，tx `0xce9d5637f82894ef2bfd2dc403664b6f143ba58b943ac3d0c7fc322fb8c47b0a`，receipt `0x1`；summary `ok=true`。
- [x] 历史样本驱动 canary 收尾核对：TDS 余额 `0`、TDS sell allowance `0`、active fuse `0`、VIRTUAL buy allowance 精确恢复为 `10 VIRTUAL`；本地 TDS 自动买入/卖出配置恢复到 disabled simulate。
- [x] `historical_live_auto_trigger_canary.py` 增加 `--sell-trigger-mode price_zero`，用于只验证“tax <= 30% 后执行自动卖出链路”，不要求当前真实成交价带来正收益；该模式只用于 canary，不代表生产卖出策略。
- [x] 2026-05-18 15:35-15:36 CST 完成远端生产库候选筛选：`TDS / VOID` 可做 direct-buy canary；`ROO / ISC / SR / SCL / ZODIAC / LUCA / F007` 当前 `eth_call/estimateGas` revert，`FIRE` pool/simulation 失败，SignalHub 未来项目当前不可买。
- [x] 远端漂移修复：同步当前 canary / buy / sell 执行脚本和 `virtuals_bot.py` 到服务器，补齐 `launch_sell_runtime_configs.custom_rules_json` 表结构；生产服务未重启，`/health` 与 `/healthz` 保持正常。
- [x] 远端 TDS 历史样本 canary 通过：sample `55` 自动买入 tx `0x0b25e9fbc0fd7dbdba92aa3411f15c25efbbcb0d1a5eae898d61959f642571c1`，sample `819` 自动卖出 tx `0xcec3e409a2ab999fb4fd6443dc5adb194793b1b717ea34eb352f2de4bb966b19`，summary `ok=true`、最终余额 `0`、active fuse `0`。
- [x] 远端 VOID 历史样本 canary 通过：sample `55` 自动买入 tx `0x11cb1c901df209424366389ec01cf6131f38daef0a76583be7c76d0f679ca90f`，sample `819` 自动卖出 tx `0xe02cd7b85b9a6973f9f40a0182d5d960985d31476d84deda9b7cec3e680fd718`，summary `ok=true`、最终余额 `0`、active fuse `0`。
- [x] 本地补充 `RRR / AURA / ASDSDA` 三个仍可交易内盘标的 canary，均用 SR `1089` 样本驱动、运行时改参热加载、小额真实买入和自动卖出，summary 均 `ok=true`；测试后已删除临时本地项目行和运行时配置，四个 token 余额/allowance 均为 `0`。
- [x] `approve_virtual_spender.py` 与 `approve_erc20_spender.py` 支持 `--force-exact`，并在 exact 模式下等待 allowance 等于目标值，修复撤销到 `0` 时确认读数可能显示旧 allowance 的问题。
- [x] 新增执行账本 `launch_execution_ledger` 与 Storage API。
- [x] `live_strategy_dry_run.py` 已把 `would_buy / pause` 写入执行账本。
- [x] `prewarmed_buy_canary.py` 支持可选账本写入 simulation / sign / broadcast / receipt 阶段摘要，不保存 raw transaction。
- [x] 新增执行熔断表 `launch_execution_fuses` 与 Storage API。
- [x] 新增执行熔断运维脚本：`scripts/ops/launch_execution_fuse.py`。
- [x] `prewarmed_buy_canary.py` 已接入 active fuse 检查：存在熔断时阻断 `--broadcast`，且不会发送交易。
- [x] canary 路径 simulation / sign / broadcast / receipt / canary 异常会触发执行熔断。
- [x] 本地验证 list / clear active fuse。
- [x] 新增生产预热执行器安全骨架：`scripts/ops/launch_prewarm_executor.py`。
- [x] 生产预热执行器支持 `simulate` / `sign-ready` / `broadcast` 三种模式。
- [x] `broadcast` 模式已接入真实发送路径：simulation green 后签名、`eth_sendRawTransaction`、receipt 验证、账本写入。
- [x] `broadcast` 模式有双门禁：`--enable-broadcast` + `VWR_ENABLE_AUTO_BUY_BROADCAST=1`；默认要求独立 `VWR_EXEC_HTTP_RPC_URL`。
- [x] `buy_virtual_canary.py` 与 `prewarmed_buy_canary.py` 优先使用独立 execution RPC；真实买入广播默认要求独立 execution RPC。
- [x] `broadcast/sign-ready` 密钥加载优先使用环境变量 `VWR_BURNER_PRIVATE_KEY`，兼容 systemd root-only `EnvironmentFile`。
- [x] `broadcast` 模式接入 active fuse、单笔上限、单项目上限、同税率档防重复发送和 broadcast/receipt 失败熔断。
- [x] `broadcast` 模式下钱包 `balance / allowance` 不足只记录 `readiness_not_ready`，不触发 active fuse；未发出交易时回滚本次策略内存状态，避免稍后转入资金后被误判为已买。
- [x] 修复 `launch_execution_ledger` 后续异常更新把已发送交易 `trade_sent=1 / broadcast_enabled=1` 覆盖回 `0` 的风险，保护同税率档防重和项目上限统计。
- [x] 生产预热执行器已接入 active fuse 检查和 simulation/sign/prewarm/broadcast/receipt 异常熔断。
- [x] 新增正常税率 live 窗口跟单策略：默认跟随 `0xe0b51bbf7af8bff0a8cd422e4b5f17aa0824969d`，按 `floor(对方消耗 VIRTUAL / 4)` 买入；优先级为普通大户策略 > 跟单策略 > 含税估算 FDV 限价单。
- [x] 跟单策略接入自动买入运行时控制：前端展示跟单买入，支持启用/停用和修改比例；执行器热加载 `followEnabled / followRatioPct`。
- [x] 生产 autobuy 模板使用 `--project-cap-scope project`，普通买入、跟单买入和 FDV 限价单共享同一个项目预算上限。
- [x] `prewarm_simulate` 模式下余额/授权不足记录为 `readiness_not_ready`，不触发 active fuse；`sign-ready` 仍会在 simulation 不绿时触发熔断。
- [x] 本地 TDS ended 烟测通过：无 intent、无签名、无广播。
- [x] 接入生产 systemd `simulate` 灰度服务：`vwr-launch-prewarm@ROO.service`，只读、不读取私钥、不签名、不广播。
- [x] 远端 ROO prewarm smoke 与健康检查通过：主服务/ROO dry-run/ROO prewarm 均 active，active fuse 为空，执行账本 `trade_sent=1` 与 `broadcast_enabled=1` 均为 `0`。
- [x] 新增并安装 ROO 生产 `broadcast` armed 服务：`vwr-launch-autobuy@ROO.service`，`broadcastEnabled=true`、`rpcSharedWithMain=false`。
- [x] ROO autobuy 服务上限已调整为单笔 `50V`、单项目 `150V`；300V 只是授权上限，不是本项目预算。
- [x] ROO 执行服务改为由 `vwr-launch-roo-start.timer` 在 `2026-05-12 22:25:00 CST` 拉起；主采集仍在 `2026-05-12 22:30:00 CST` 自动进入 `prelaunch`。
- [x] 2026-05-11 远端验证：ROO timer `active(waiting)`，下一次触发 `2026-05-12 22:25:00 CST`；执行服务在 timer 触发前为 `inactive + disabled`，active fuse 为空，ROO `tradeSent=true` 计数为 `0`。
- [x] 接入生产自动卖出常驻执行器 `scripts/ops/launch_sell_executor.py`。
- [x] 接入 ROO autosell armed systemd 服务：`vwr-launch-autosell@ROO.service`，由 `vwr-launch-roo-start.timer` 与买入执行服务一起拉起。
- [x] autosell 支持执行账本状态重建、真实余额读取、sell simulation、精确 token approve、broadcast gate、receipt/fuse 处理。
- [x] 本地 TDS ended autosell 只读 smoke 通过：`no_position`，无签名、无广播。
- [x] 新增 autosell 状态重建测试：`scripts/ops/test_launch_sell_executor.py`。
- [x] 2026-05-15 状态校准：当前生产部署已包含 Phase 053/054 代码与文档同步；具体部署 commit 以服务器 `DEPLOYED_COMMIT` 为准。`writer / realtime / backfill / SignalHub / nginx` 均 active，`/health ok=true`，`queueSize=0`，`pendingTx=0`，`runtimePaused=false`，`/healthz status=ok`。
- [x] 真实 live 项目窗口内验证 BuyIntent -> simulation/prewarm/broadcast/receipt 的完整路径：2026-05-15 复核 ROO 生产账本与链上 receipt，2 笔真实买入均 `receipt_success / status=0x1`。
- [x] 真实 live 项目窗口内验证 SellIntent -> approval/simulation/broadcast/receipt 的完整路径：2026-05-15 复核 ROO 生产账本与链上 receipt，2 笔真实卖出均 `receipt_success / status=0x1`，包含精确 approve 后卖出。
- [ ] 如需真正买满 ROO 150V 项目预算，需要把足够 VIRTUAL 转入 burner；授权已到 300V，服务上限已收紧为 150V。
- [ ] 生产预热热路径：提前维护 nonce、fee、gas、allowance、balance，tick 到达时只做本地判断和广播。
- [x] 2026-05-20 生产机 RPC 压力观察通过：以 `/etc/virtuals-whale-radar/execution-rpc.env` 注入独立 execution RPC，TDS 只读 probe `green=true`、`executionRpcSharedWithMain=false`、execution p90 `153.5ms`，报告 `data/backtests/phase-061-rpc-pressure-TDS-20260520.json`。

## Phase 54：大户榜单团队地址过滤与管理员纠偏

- [x] 新增 Phase 054 子 plan：`docs/phases/phase-054-team-address-filter-plan.md`。
- [x] 新增 Phase 054 子 todo：`docs/phases/phase-054-team-address-filter-todo.md`。
- [x] 新增 `team_address_overrides` 表。
- [x] 新增管理员覆盖规则 API。
- [x] overview 榜单返回团队过滤状态和覆盖来源。
- [x] 主大户榜单过滤掉 `costExcluded=true` 地址。
- [x] 管理员新增唯一默认折叠的“自动过滤”控件。
- [x] 大户榜单表格不展示团队/疑似团队地址。
- [x] 大户榜单表格不展示“团队过滤”字段或行内过滤按钮。
- [x] 管理员支持输入钱包地址和备注加入排除。
- [x] 管理员支持把审核区地址纳入成本位。
- [x] 覆盖优先级固定为：手动排除 > 手动纳入 > 自动识别。
- [x] 新增首分钟零税且当时预期应有税的硬过滤规则，不再要求买入份额阈值。
- [x] 本地 Python 语法、前端 build、lint、API 和 UI 流程验证通过。
- [x] 验证 `0x81f7ca6af86d1ca6335e44a2c28bc88807491415` 会被自动过滤。
- [x] 修复手动排除后“纳入成本位”按钮因 pending wallet 残留而无法点击的问题。
- [x] 同步前做完整 `git diff` 审核。
- [x] 2026-05-15 状态校准：当前生产部署已包含团队过滤表、管理员覆盖 API 和前端相关代码；生产服务健康。
- [x] 代码已随生产安全同步进入远端。
- [x] 生产 overview API 烟测通过：管理员短期 session 只读访问项目列表与 ROO overview，返回 `ok=true`、`whaleBoard=20`、`trackedWallets=6`、`hiddenTeamRows=1`。
- [x] 生产管理员项目详情页 UI 浏览器复测通过：ROO 详情页返回 200，未回登录页，页面包含 `ROO`、`打新成本位`、`自动过滤`，前端 error 数为 0。
- [x] 将 Phase 053 的团队/初始化 route 识别接入自动过滤：事件入库持久化 `tx_to / tx_selector / calldata_bytes`。
- [x] 自动过滤规则新增高置信条件：`to == direct router`、`selector == 0x214013ca`。
- [x] 回放验证 SR/ISC/TDS：团队/初始化地址应被过滤，普通 `0x706910ff` direct buy 不误杀；报告见 `docs/phases/phase-054-route-filter-validation-2026-05-15.md`。

## Phase 55：自动买入运行时控制台

- [x] 新增 Phase 055 子 plan：`docs/phases/phase-055-runtime-strategy-control-plan.md`。
- [x] 新增 Phase 055 子 todo：`docs/phases/phase-055-runtime-strategy-control-todo.md`。
- [x] 2026-05-20 新增生产逼近测试 runbook：`docs/phases/phase-055-live-window-production-like-test-runbook.md`。
- [x] 新增 `launch_strategy_runtime_configs` 表。
- [x] 新增 `launch_strategy_runtime_config_audit` 审计表。
- [x] 新增管理员读取/保存运行时策略配置 API。
- [x] 项目详情页新增管理员专用“自动买入控制”模块。
- [x] 支持恢复默认 `25/50/50/150` 与 `20/10` 阈值。
- [x] 支持编辑基础买入、抄底买入、抄底阈值、横盘暂停阈值、单笔上限和项目预算。
- [x] 2026-05-20 删除“含税估算 FDV 上限”的前端入口和执行器依赖；旧字段仅保留 DB/API 兼容。
- [x] 2026-05-20 新增独立“含税估算 FDV 限价单”：可配置多个订单，触发后速度优先连续广播，并在后续循环补查成交结果。
- [x] 自动买入 UI 重构为“买入策略卡”：买入触发条件只读展示，金额、节奏、抄底放大和风险上限分区编辑。
- [x] 买入触发条件前端只展示当前后端策略事实，不新增提交字段，不改策略逻辑。
- [x] 合并展示 `有效榜单 20 人 / 5 个成本样本`，并解释榜单人数和成本样本不是同一件事。
- [x] 前端收敛为 `恢复默认`、`保存并启用`、`停用自动买入`，隐藏 mode/updatedReason 等原生字段。
- [x] `launch_prewarm_executor.py` 支持配置热加载。
- [x] 配置缺失时沿用 CLI/systemd 默认值。
- [x] `enabled=false` 或 `mode=simulate` 时阻断真实买入。
- [x] 配置版本变化时写入 `strategy_config_reloaded`。
- [x] 静态风控校验：买入金额不能超过单笔上限，项目预算不能低于已发送买入 V。
- [x] 本地验证：Python `py_compile`、`test_launch_execution_pipeline.py`、`test_launch_prewarm_executor.py`。
- [x] 前端验证：`npm run build`、`npm run lint`。
- [x] 2026-05-20 限价配置验证：新增单测覆盖高于限价跳过、等于限价继续买入，执行器热加载可读取限价配置；前端生产构建通过。
- [x] 本地管理员页面浏览器烟测：`/admin/projects/1?project=TDS` 可渲染“自动买入控制”，主要动作收敛为恢复默认、保存并启用、停用自动买入。
- [x] 本地 HTTP 保存烟测：POST simulate `100/200/200/300` 成功后重置为 disabled `25/50/50/150`。
- [x] 新增本地发射模拟入口 `scripts/ops/runtime_control_launch_simulator.py`，只读验证前端保存的运行时参数会被执行器在后续 tick 热读。
- [x] 2026-05-20 `runtime_control_launch_simulator.py` 扩展为同时验证独立含税估算 FDV 限价单：每个 tick 重新读取 `launch_fdv_limit_orders`，前端/API 创建、删除、更新后下一 tick 生效。
- [x] TDS 小额参数网页保存与 100x 完整窗口 paper replay 通过：`version=22` 使用 `0.1/0.2/0.2/0.6`，触发 `0.1/0.2/0.1/0.2 VIRTUAL` 四次买入意图，预算 `0.6 VIRTUAL` 生效后阻断后续意图；测试后停用为 `version=23`。
- [x] 2026-05-20 TDS 限价单 L5 小额真实广播 canary 通过：模拟 `LIVE` sample 触发临时限价单 `FDV <= 120 万 USD / 买入 0.01 VIRTUAL`，tx `0x0b707eedd76e8c694ff43bfba2e8b4c3b407ca26759ffd290432fe18c61ccb9e` receipt `0x1`，限价单 `id=5` 已 `filled`，账本 `receipt_success`；随后测试仓位已卖回 VIRTUAL，卖出 tx `0xd4cfccda71debeda1946f9450af693a0dda26a7c7692bc4582bdafc4fa73e54e` receipt `0x1`，最终 TDS 余额 `0`、TDS 授权 `0`。
- [x] 2026-05-20 TDS 限价单前端/API 热更新 L2 验证通过：管理员 HTTP API 创建临时限价单 `id=8` 后，模拟执行器下一 tick 输出 `paper_fdv_limit_order_intent`；更新阈值后下一 tick 不触发；删除后订单变为 `canceled / enabled=false`；TDS runtime config 已恢复 `enabled=false / mode=simulate`。
- [x] 2026-05-20 自动买入速度优先优化：限价单触发后同 tick 跳过普通自动买入；普通买入广播后不等待 receipt，由后台补查更新账本；生产 autobuy 模板默认使用 `--no-wait-receipt` 和 `0.1s` live poll；本地 `py_compile`、`test_launch_prewarm_executor.py`、`test_launch_execution_pipeline.py` 通过。
- [x] 2026-05-20 自动买入预签候选交易池：新增默认关闭的 `--enable-signed-candidate-cache`，后台预先 bind/simulate/sign，触发时命中候选后直接广播；raw tx 只保存在内存，同批候选命中一次后清空，避免 nonce 复用；本地 `py_compile`、`test_launch_prewarm_executor.py`、`test_launch_execution_pipeline.py` 通过。
- [x] 2026-05-20 预签候选交易池生产 canary 通过：TDS sign-ready 命中候选不广播；随后 `0.001 VIRTUAL` 小额真实买入 tx `0xe3d385a3079f621c490c76173e6dd774cfb8acb5170fc761d02f52299dddc2fb` receipt `0x1`，`triggerToSendAckMs=246.2ms`；测试仓位已卖回，TDS 余额/授权 `0`，active fuse `0`。
- [x] 2026-05-20 生产 autobuy systemd 模板启用预签候选缓存：`ttl=5s / refresh=0.5s / maxCount=1`；当前 MTR autobuy 服务仍 inactive，未 armed。

## Phase 56：自动卖出运行时控制台

- [x] 新增 Phase 056 子 plan：`docs/phases/phase-056-runtime-autosell-control-plan.md`。
- [x] 新增 Phase 056 子 todo：`docs/phases/phase-056-runtime-autosell-control-todo.md`。
- [x] 新增 `launch_sell_runtime_configs` 表。
- [x] 新增 `launch_sell_runtime_config_audit` 审计表。
- [x] 新增管理员读取/保存自动卖出配置 API。
- [x] 项目详情页新增管理员专用“自动卖出控制”模块。
- [x] 支持恢复默认税率窗口、冷却、事件回看窗口和默认卖出规则。
- [x] 支持编辑税率窗口、冷却时间、事件回看窗口和条件组合式自定义卖出规则。
- [x] 支持规则构建器：每条规则可添加价格、大单、收益条件，并选择 `AND / OR`。
- [x] 兼容旧的限价卖出、大单卖出、高收益率卖出、收益率 + 大单配置。
- [x] 大单门槛单位支持 `VIRTUAL / USD`；限价单位支持 `USD / VIRTUAL`。
- [x] 后端保存 `custom_rules_json`，保存前做类型、单位、阈值和卖出比例校验。
- [x] 前端收敛为 `恢复默认`、`保存并启用`、`停用自动卖出`，隐藏 mode/updatedReason 等原生字段。
- [x] `launch_sell_executor.py` 支持配置热加载。
- [x] 配置缺失时默认阻断真实卖出。
- [x] `enabled=false` 或 `mode=simulate` 时阻断真实卖出。
- [x] 配置版本变化时写入 `sell_config_reloaded`。
- [x] `DualSellConfig` 支持运行时卖出一档/二档比例。
- [x] `CustomSellConfig/evaluate_custom_sell` 支持条件组 `AND/OR` 和多规则同时触发，卖出增量累加但不超过原始仓位 `100%` 或当前钱包余额。
- [x] 大单条件按 `rule_id + tx_hash` 去重，避免同一笔大单重复触发同一规则。
- [x] 本地验证：Python `py_compile`、`test_launch_execution_pipeline.py`、`test_launch_sell_strategy.py`、`test_launch_sell_executor.py`。
- [x] 前端验证：`npm run build`、`npm run lint`。
- [x] 本地执行器热加载探针：保存探针配置后，`launch_sell_executor.py` 记录 `sell_config_reloaded`，随后恢复 disabled 默认配置。

## Phase 57：Base 生态钱包与链上积分支付

- [x] 将当前 Base 登录从单一 Base Account SDK 抽象为多钱包入口，保留 Base Account 作为默认 Base App 入口。
- [x] 新增 OKX Wallet 登录入口：检测 EVM provider、切换 Base Mainnet、签名 SIWE 消息，复用后端钱包验签与 session 创建。
- [x] 后端钱包认证支持 `base_wallet / okx_wallet / injected_wallet` 来源；同一钱包地址优先复用已有用户，避免同一地址在不同钱包入口重复建号。
- [x] 钱包登录成功后自动写入 `user_wallets`，继续复用用户端钱包持仓追踪链路。
- [x] 新增 Base USDC 链上充值 intent 表，记录用户、套餐、积分、USDC 金额、收款地址、付款钱包、过期时间、tx hash 和入账流水。
- [x] 用户端 `Billing` 增加“Base USDC 支付”路径：用户选择套餐后从钱包发起 USDC transfer，后端验 receipt 后自动写入 `credit_ledger`。
- [x] USDC 入账只验证 Base chain `8453`、Base 原生 USDC、收款地址、金额、付款钱包和 tx 去重；不做 `approve + transferFrom`。
- [x] 后端验证 tx hash 时轮询等待 Base RPC receipt，避免钱包刚返回 tx hash 就误报 `transaction receipt not found yet`。
- [x] 钱包返回 tx hash 后先记录到 payment intent，便于 receipt 暂未索引时回溯；本地开启 `0.01 USDC` 小额实测套餐。
- [x] 没有显式配置 `BILLING_USDC_RECEIVER` 时禁用链上支付，避免默认转入监控钱包或策略钱包。
- [x] 保留微信/管理员手动入账作为备用运营路径。
- [x] 新增 x402 试点面：为 agent 提供可发现的付费数据 API 描述，第一步返回 HTTP `402 Payment Required`、`PAYMENT-REQUIRED` header 与 `eip155:8453` payment requirements；完整 facilitator settlement 作为后续增强。
- [x] 本轮不改自动买入、自动卖出、execution RPC、fuse、launch scheduler 和生产广播链路。

## Phase 58：Billing 20 积分与 Base 支付口径整理

- [x] 每个项目首次解锁成本从 `10` 积分调整为 `20` 积分。
- [x] 充值套餐按项目成本重排：`starter=20 积分 / 2.00 USDC`，`value=100 积分 / 8.00 USDC`。
- [x] `Billing` 页面改为账户状态、套餐选择、支付说明、未到账帮助二维码的两栏布局。
- [x] Virtuals 邀请码继续保留为官方注册链接，但不在本产品内展示“后续付费一律五折”的自动优惠承诺。
- [x] 联系二维码使用真实图片资源，并在前端增加固定白底展示区域和 placeholder 兜底，避免图片加载失败时显示空白。

## Phase 59：Base 欢迎页与品牌图标路径整理

- [x] 修复本地 Vite dev 下 `/admin/brand/logo-mark.png` 返回 HTML 导致品牌图标破裂的问题。
- [x] 新增 `BrandLogo` 组件，自动在 `/brand/logo-mark.png` 与 `/admin/brand/logo-mark.png` 之间兜底。
- [x] Base Account SDK 的 `appLogoUrl` 改用当前环境的正确品牌图标 URL。
- [x] `/base` 收敛为公开欢迎页，只保留一个“开始使用”入口，不再重复展示钱包登录按钮，文案重心保持在 Virtuals。
- [x] `/auth/login` 收敛为统一登录入口，同页支持 Base Account、OKX Wallet 和邮箱密码。
- [x] 未登录访问业务页统一跳转 `/base?redirect=...`，登录后回到原目标。
- [x] `/auth/register` 明确为邮箱注册页，注册文案按 20 积分解锁 1 个项目更新。
- [x] 欢迎页数据优先展示远端生产库核对过的 `SR` 真实样本：`602` 买入事件、`185` 参与钱包、峰值分钟约 `96.8k V`、累计税收约 `448.3k V`。
- [x] 欢迎页案例表改为 `SR 大户榜单`，展示钱包地址、累计花费、累计代币数量和含税成本 FDV，突出产品核心能力。
- [x] 欢迎页指标文案统一为中文：`SR 买入事件 / 参与钱包 / 峰值分钟消耗 / 累计税收`。

## Phase 60：Base 生态入口生产收口

- [x] Billing 增加链上支付记录：展示当前用户最近 Base USDC payment intents、状态、金额、创建时间和 BaseScan 交易入口。
- [x] 用户刷新页面或 receipt 暂未返回后，可以在 Billing 对同一笔 tx hash 重新确认入账；无 tx hash 的待付款 intent 可粘贴交易哈希找回。
- [x] 后端新增 `GET /api/app/billing/onchain-intents`，用于读取当前用户最近链上支付记录。
- [x] 已记录 tx hash 的 intent 即使超过普通 intent TTL，也允许继续验证同一笔 tx，避免 receipt 延迟导致用户已付款但无法入账。
- [x] 钱包登录身份与用户追踪钱包拆分：新增 `wallet_auth_identities`，钱包登录只信任签名验证后的认证身份，不再把 `user_wallets` 里的任意追踪地址当作登录归属。
- [x] 同一钱包地址通过 Base Account / OKX Wallet / injected wallet 登录时，优先复用已有钱包认证身份；历史钱包用户通过 synthetic wallet email 兼容回收。
- [x] 修复 OKX Wallet 登录成功后停留在登录页的问题：钱包登录成功后先写入本地 auth cache 并立即执行跳转，接口刷新改为后台执行，同时保留浏览器级跳转兜底。
- [x] 2026-05-20 生产站 Base USDC 支付由 operator 实测通过，积分到账正常；Base 外部分发仍暂停，主线继续回到自用实盘盈利闭环。
- [x] 整理 Base 生态上架资料包：`docs/base-ecosystem-listing.md`。
- [x] 本地验证：`py_compile`、钱包认证身份临时库探针、`npm run lint`、`npm run build`、浏览器验证 `/base` 与 `/app/billing`。

## Phase 52：双策略自动卖出回测

- [x] 明确卖出观察窗口：税率 `<=30%`。
- [x] 2026-05-13 根据 ROO live 修正卖出口径：收益率和大额买入不再独立 OR 触发，必须同时满足。
- [x] 明确双条件触发：税率 `<=30%` 且单笔买入 `>=5,000 VIRTUAL` 且自身收益率 `>=30%`，卖总仓位 `30%`。
- [x] 明确升档触发：税率 `<=30%` 且单笔买入 `>=8,000 VIRTUAL` 且自身收益率 `>=50%`，卖总仓位 `50%`。
- [x] 明确目标计算：有效卖出目标取收益率档位与大额买入档位的较低值；仅收益率达标或仅大额买入都不卖出。
- [x] 修正回测事件窗口：与生产 autosell 一致，默认查看最近 `120 秒`内未处理的大额买入。
- [x] 修正执行账本审计字段：同一 intent 从 simulate 走到 broadcast/receipt 时同步升级 `mode`，避免出现 `prewarm_simulate + trade_sent=1` 的假象。
- [x] 新增纯策略模块：`scripts/ops/launch_sell_strategy.py`。
- [x] 新增单元测试：`scripts/ops/test_launch_sell_strategy.py`。
- [x] 新增 SR/ISC 回测脚本：`scripts/ops/recalc_dual_sell_strategy.py`。
- [x] 输出回测报告：`docs/phases/phase-052-dual-sell-strategy-2026-05-11.md`。
- [x] 加固余额不足保护：真实余额低于目标卖出数量时，只按实际卖出的原始仓位比例更新策略状态。
- [x] 修复 `sell_virtuals_token.py` 输出：`broadcastRequested` 真实反映 `--broadcast`，receipt 输出包含 `receiptOk / reason`。
- [x] 补齐 `deploy_production_safe.sh` 白名单：execution RPC、pressure probe、sell strategy、sell 回测、Phase 052/053 报告和相关测试脚本都会随生产同步脚本带上。
- [x] 本地验证：`py_compile`、策略单元测试、SR/ISC 回测、`git diff --check`。
- [x] Phase 053 已接入生产自动卖出执行链路：执行账本状态、真实余额读取、sell simulation、精确 token approve、broadcast gate、receipt/fuse。

## Phase 53：Live 发射档案与回测复用

- [x] 新增标准归档脚本：`scripts/ops/archive_launch_project.py`。
- [x] 归档脚本只读取 `SQLITE_PATH` 或显式 `--sqlite-path`，不解析 RPC 环境变量占位，支持 SSH 手工运行。
- [x] 归档输出包含：`manifest.json`、`project.json`、`samples.jsonl`、`events.jsonl`、`execution-ledger.jsonl`、`fuses.jsonl`、`summary.json`、`archive.db`。
- [x] `live_strategy_dry_run.py` 新增 `--full-samples-jsonl`，每轮采样单独写入全量 sample 文件。
- [x] 新增生产只读 recorder 模板：`deploy/systemd/vwr-launch-dryrun@.service`。
- [x] `deploy_production_safe.sh` 白名单加入 archive 脚本和 dry-run recorder 模板。
- [x] `recalc_dynamic_buy_strategy.py` 支持 `--report <archive>/summary.json`。
- [x] `recalc_dual_sell_strategy.py` 支持 `--report <archive>/summary.json --rule <rule>`。
- [x] 本地 smoke：TDS 本地 DB 可导出 archive；指定本地 sample JSONL 后 dynamic/dual sell 回测可读取 archive summary。
- [x] 2026-05-16 ROO live regression 标准归档完成：`sampleCount=7993`、`eventCount=505`、`ledgerCount=240`、`warnings=[]`。
- [x] 2026-05-16 ROO canonical 买入回放完成：当前主策略买入 `6` 次，总投入 `150V`，最终收益率 `+31.8845%`。
- [x] 2026-05-16 ROO canonical 卖出回放完成：卖出 `1` 次，最终收益率 `+32.7369%`，相对纯持有提升 `+0.846%`。
- [x] 2026-05-16 重新查链确认 ROO 2 笔买入与 2 笔卖出 receipt 均为 `status=0x1`。
- [x] 新增通用 live 项目启动编排脚本：`scripts/ops/schedule_launch_services.py`。
- [x] 新增本地 prewarm systemd 模板：`deploy/systemd/vwr-launch-prewarm@.service`。
- [x] 新增通用启动编排测试：`scripts/ops/test_schedule_launch_services.py`。
- [x] 2026-05-24 ORION 使用 `schedule_launch_services.py --project ORION --start-at "2026-05-26 00:00:54" --services open-sniper,fdv-limit --apply` 创建启动与归档 timer。
- [x] 新增无狙击税开盘秒买执行器 `scripts/ops/launch_open_sniper_executor.py`，并完成本地/远端 smoke、压测和 no-tax 官方上下文核验。
- [x] 新增生产模板 `deploy/systemd/vwr-launch-open-sniper@.service` 与 `deploy/systemd/vwr-launch-fdv-limit@.service`；ORION start timer 会在 `2026-05-25 23:30:54 CST` 拉起。
- [x] ORION 生产核验：timer enabled，open-sniper/fdv-limit 服务当前 inactive 等待 timer，`/health` 与 `/healthz` 正常。
- [x] 2026-05-24 15:49 CST ORION preflight：core workflow ready，execution RPC 分离，active fuse `0`，allowance `300V` 和 Base ETH gas 充足；当前 burner VIRTUAL 约 `1.67V`，不足首笔 `100V`，发射前必须转入足额 VIRTUAL。
- [x] 2026-05-24 15:49 CST ORION 暂无含税 FDV 限价单；`fdv-limit` 服务会启动但无订单可执行。
- [x] 明确 ORION 无税自动卖出：默认关闭、用户手动开启；`1%` 税率天然满足 `max_tax_rate=30`，不再单独设置 `tax<=5%`；配置保持 `dual_roi_large_buy_sell + customRules=[]`，冷却 `10s`、大单回看 `30s`、卖出目标仓位 `30%/50%`。
- [x] 2026-05-24 21:31 CST 将 ORION timer 扩展到 `open-sniper,fdv-limit,autosell`，并写入 disabled 的 ORION 自动卖出运行时配置；只读 autosell 检查输出 `runtime_config_disabled`，生产健康正常。
- [x] 2026-05-26 ORION open-sniper 复盘修复：high/ultra 阶段按 `presign_refresh_sec` 持续重签，生产模板 `10s -> 0.5s`；开盘后命中报价失效 selector 立即重签并同轮复探。
- [x] 2026-05-26 二次修正 open-sniper 执行语义：无税开盘秒买不再绑定开盘前池子报价，改为 direct buy calldata，`amountOutMin=1`，用极低最小到账表达市价抢买；普通 taxed 策略和 FDV 限价单仍保留报价/限价保护。
- [x] 2026-05-26 远端 ORION 项目级 drop-in 已同步修复：保留 `300V` 与 `5/6 gwei`，补齐 `--presign-refresh-sec 0.5` 和 `--requote-revert-selectors 0x850c6f76`，避免实例覆盖模板后继续走旧参数。
- [x] 2026-05-26 open-sniper 增加显式准点直发开关 `--post-trigger-direct-fire`，默认关闭，避免官方时间到但链上仍关闭时烧 nonce。
- [x] 2026-05-26 open-sniper 最优版热路径：广播后短窗口确认 receipt/nonce；未确认时同 nonce 自动提高手续费重新 fanout。FDV 限价单新增 `--require-open-sniper-before-fdv-limit`，无税项目可先等首笔 open-sniper 发出，再放开限价单；调度脚本同时选择 `open-sniper,fdv-limit` 时会自动生成 gate drop-in。
- [x] 2026-05-26 通用无税秒狙击 profile：`schedule_launch_services.py --auto-profile` 读取官方 `launchInfo`，no-tax 自动选 `open-sniper,fdv-limit,autosell`，60s/98m 走正常服务，未知税率阻断；本地 TDS dry-run 验证识别为 `taxed_60s`。
- [ ] 下一次真实 live 项目结束后，检查 archive `sampleCount/eventCount/ledgerCount`，并确认 `launch-samples-<SYMBOL>.jsonl` 正常增长。

## Phase 61：自用实盘盈利闭环

- [x] 合并 `codex/base-ecosystem-probe` 到 `main`，让 `main` 对齐当前生产基线。
- [x] 明确暂停 Base 生态上架、Base App / 比赛提交、外部用户体验继续打磨。
- [x] 明确暂停用户提前授权自动交易、普通用户自定义买卖单、用户钱包自动执行。
- [x] 梳理当前 operator 实盘工作流：项目发现、发射前配置、执行服务启动、实时观察、自动买入、自动卖出、归档、复盘；见 `docs/phases/phase-061-operator-profit-workflow.md`。
- [x] 设计下一次真实 live 项目的操作清单：需要提前设置的项目、timer、runtime 参数、资金、RPC、fuse 和回滚动作。
- [x] 将真实窗口复盘标准化为一页报告：买入原因、买入条件、成交税率/FDV、卖出触发、最终 PnL、失败点、下一次策略调整。
- [x] 完成第一项实盘链路短板收口：生产 execution RPC 压力观察通过，确认执行 RPC 与主采集 RPC 分离。
- [x] 2026-05-20 从生产 SignalHub upcoming feed 选出 `PROFIT` / `MTR` 候选，并记录到 `docs/phases/phase-061-live-candidates-2026-05-20.md`。
- [x] 对 `PROFIT` / `MTR` 完成非广播 prewarmed buy 模拟：均未广播、未发送交易；当前 direct buy 在发射前 revert，25 V 预算还需要提前提高 VIRTUAL 授权。
- [x] 选择 `MTR` 作为第一次只读 runbook 演练对象：已加入生产 managed/watch，并创建 `dryrun,prewarm` 启动 timer 与归档 timer。
- [x] 2026-05-20 11:15 CST 复查 MTR：生产健康、timer、fuse 与 execution RPC 均正常；readiness 仍为 `ready=false`，5V 也因未到可交易状态 revert，25/50V 还需提高 allowance。
- [x] 2026-05-21 修复聚合器买入漏解析：`ETH/WETH -> VIRTUAL -> 内盘买入` 路径旧 parser 因路由合约净 VIRTUAL 流出为 `0` 被误判为非买入；`parse_receipt_for_launch` 已按 launch outflow 兜底。已对当前生产库全部具备 `token_addr + internal_pool_addr` 的受管项目执行全窗口 replay，MTR `86 -> 319`、ROO `505 -> 938`、TDS `128 -> 265`、ISC `322 -> 513`、SR `602 -> 655`，所有项目 final audit 均 `green / repair=0`。
- [ ] 若要把 MTR 从只读演练升级为真钱实盘，先确认预算、授权、自动买入/自动卖出 timer 范围。
- [ ] 下一次真实 live 项目按 Phase 061 runbook 创建启动与归档 timer，并在窗口后完成一页复盘。
