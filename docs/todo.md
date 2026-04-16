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
- [x] 未登录访问业务页时统一跳转 `/auth/login`。
- [x] 用户端固定为 `Overview / Projects / SignalHub / Wallets / Billing` 五页。
- [x] 管理员端新增 `Users` 页面。
- [x] 用户端只有 `Wallets` 可编辑，其余页面只读。
- [x] 用户钱包数据彼此隔离，管理员可查看全部用户钱包。
- [x] 管理员默认不直接查看完整密码哈希，只提供密码状态和重置能力。
- [x] 初始管理员账号通过配置或环境变量 bootstrap 创建。
- [x] 用户查看某个项目 `Overview` 详细数据时，按“每用户、每项目首次解锁”扣 `10` 积分，解锁后永久可看。
- [x] 新用户注册赠送 `20` 积分。
- [x] 充值方案固定为：`10 积分 = 10 元`、`50 积分 = 40 元`。
- [x] 用户端 `Projects / SignalHub` 免费可看，未解锁项目的 `Overview` 详细数据不可看。
- [x] 用户积分不足时，点击未解锁项目应引导到 `Billing`。
- [x] `Billing` 页面展示联系方式二维码，不接入在线支付。
- [x] `Billing` 顶部固定展示邀请文案与注册链接。
- [x] 管理员调整积分时只允许“加积分 / 扣积分 + 备注”，不直接裸改余额。
- [x] 管理员端补充 `Operations` 一级页面，用于处理充值申请和通知流转。
- [x] 用户提交充值申请时必须上传图片凭证，后端按附件归档保存。
- [x] 用户通知支持 `未读 / 已读 / 全部已读`，并在顶栏显示未读提醒。
- [x] 当前默认充值流程改为：微信付款后管理员直接手动入账，不要求用户在 App 内提单。

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
- [x] 将图表默认时间区间绑定到项目 `start_at / resolved_end_at`。
- [x] 重构 Whale Board，字段固定为：
  - 钱包地址
  - 累计花费 V
  - 累计代币数量（万）
  - 成本（万）
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
- [x] 完成未登录跳转 `/auth/login`。
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
  - `Virtuals 新用户使用邀请码注册，后续付费一律五折`
  - `https://app.virtuals.io/referral?code=LFfW5x`
- [x] 在 `Billing` 页面展示：
  - 当前积分
  - 累计消耗积分
  - 已解锁项目数
- [x] 在 `Billing` 页面展示固定套餐：
  - `10 积分 / 10 元`
- `50 积分 / 40 元`
- [x] 在 `Billing` 页面展示联系方式二维码与联系说明。
- [x] 用户点击购买时只弹出联系方式二维码，不接入在线支付。
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
- [x] 验证未登录访问 `/app/*` 与 `/admin/*` 会跳到 `/auth/login`。
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
- [x] 充值链路已收敛为“微信付款 + 管理员手动入账”的轻模式。
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
- [ ] 将 `tax-only` fallback 作为正式生产规则提交到 GitHub 并同步服务器。
