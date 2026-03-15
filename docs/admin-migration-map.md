# 管理员后台迁移对照表

## 旧页面区块到新页面映射

| 旧区块 | 旧位置 | 新位置 | 说明 |
| --- | --- | --- | --- |
| 顶部项目切换 | `dashboard.html` header | `/admin` Top Bar | 统一为全局项目上下文，URL 持久化 |
| 刷新 / 采集开关 / 刷新模式 | `dashboard.html` header | `/admin` Top Bar | 仅保留高频动作 |
| 运行状态卡 | 首页中部 | `Overview` | 成为首页第一屏健康摘要 |
| DB 批量调节 | 首页中部 | `Operations` | 从首页移除 |
| 项目配置管理 | 首页中部 | `Projects` -> `Project Settings` Sheet | 不再常驻展开 |
| SignalHub 卡片 | 首页中部 | `SignalHub Inbox` | 升级为完整收件箱页面 |
| KPI 区 | 首页下半部分 | `Overview` + `Projects` | 全局 KPI 放 Overview，项目 KPI 放 Projects |
| 分钟图 | 首页下半部分 | `Projects` | 页面主视觉模块 |
| 大户榜 | 首页下半部分 | `Projects` | 与项目分析同页 |
| 我的钱包持仓 | 首页下半部分 | `Wallets` + `Projects` 预览 | 全量管理拆页，项目页保留预览 |
| 交易录入延迟 | 首页底部 | `Overview` + `Operations` | 首页看快照，运维页看详细表 |

## 旧状态到新状态映射

| 旧状态来源 | 新方案 |
| --- | --- |
| `virtuals_selected_project` localStorage | URL `?project=` 为主，localStorage 仅做 fallback 与 legacy 同步 |
| `virtuals_refresh_mode` localStorage | 新后台继续保留，但由 Top Bar 控制 |
| 扫描时间区间 localStorage | `Operations` 页面本地表单 + URL |
| 分钟图时间区间 localStorage | `Projects` 页面 URL `minuteStart` / `minuteEnd` |
| SignalHub 零散 message 文案 | 统一为 `未同步 / 可导入 / 草稿待补全 / 已导入 / 导入失败` |

## API 对照

| 接口 | 新用途 |
| --- | --- |
| `/meta` | 全局项目、固定参数、runtime tuning、SignalHub 配置 |
| `/health` | Overview 顶部状态、Top Bar 状态、Operations 状态 |
| `/signalhub/upcoming` | Inbox 列表与 Overview upcoming 预览 |
| `/launch-configs` | Projects 配置 Sheet、Inbox 激活导入 |
| `/wallet-configs` | Wallets 页面钱包配置 |
| `/wallet-recalc` | Wallets 页面重算 |
| `/runtime/pause` | Top Bar 与 Operations 开关 |
| `/runtime/db-batch-size` | Operations 页面 |
| `/scan-range` / `/scan-jobs/*` | Operations 页面回扫 |
| `/mywallets` | Projects 钱包预览、Wallets 页面表格 |
| `/minutes` | Projects 分钟图 |
| `/leaderboard` | Projects 大户榜 |
| `/event-delays` | Overview 快照、Operations 明细 |
| `/project-tax` | Overview KPI、Projects 税收模块 |

## 当前结论

- 新后台入口已经固定为 `/admin`，旧后台保留 `/dashboard`。
- `Overview` 负责全局状态和导航，不再承担配置录入。
- `SignalHub Inbox` 成为唯一的 upcoming 导入入口。
- `Projects` 成为项目分析与配置入口。
- `Wallets` 与 `Operations` 已在这次实现中一并落地，不再只停留在 legacy。
