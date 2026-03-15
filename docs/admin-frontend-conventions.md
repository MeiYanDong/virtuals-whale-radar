# 管理后台前端实现约定

## 技术栈

- 工程目录：`frontend/admin/`
- 运行时：`React + Vite + TypeScript`
- 样式层：`Tailwind CSS v4`
- 组件层：`shadcn/ui` 风格组件 + Radix primitives
- 数据层：`TanStack Query`
- 路由层：`React Router`
- 通知：`sonner`
- 图表：`recharts`

## 目录规则

- `src/app/`：应用壳层、上下文、路由级结构
- `src/api/`：请求客户端、query keys、后端接口封装
- `src/adapters/`：旧 API 到前端稳定模型的转换
- `src/components/`：通用页面组件、ui primitives、图表组件
- `src/pages/`：一级页面
- `src/lib/`：格式化、工具函数
- `src/types/`：接口类型定义
- `src/styles/`：全局 token、基础样式

## 状态管理规则

- 服务端数据优先使用 `TanStack Query`
- 当前项目、页面筛选、时间区间优先写入 URL
- localStorage 只保留偏好型状态或兼容 legacy 的桥接状态
- 旧字段不直接在页面里消费，必须先经过 `api/` + `adapters/`

## 设计系统规则

- 品牌主色：青绿系 `#248E93`
- 背景：浅薄荷系 `#F2F8F3`
- 侧栏与图表必须沿用同一套主题 token
- 不允许新增旧版荧光绿、黑底霓虹、重型科技看板风格
- 高风险动作使用 destructive button 或警示 alert，不允许只靠文案提示

## 组件规则

- 页面框架统一使用 `PageHeader + SectionCard + 语义化数据模块`
- 按钮、卡片、Badge、Dialog、Sheet、Table 必须使用统一 ui primitives
- 异步动作统一使用 toast + inline state
- 页面必须完整覆盖 loading / empty / error 三态

## 后端接线规则

- 生产环境前端构建输出到 `frontend/admin/dist/`
- Python 服务负责 `/admin` SPA 入口、`/admin/assets/` 静态资源、`/admin/brand/` 品牌资源
- 旧 `/dashboard` 不移除，作为回退入口保留

## Heartbeat 约定

- UI heartbeat 现在仅作为 telemetry，不再决定 runtime 是否自动暂停
- runtime 是否暂停只跟随手动开关
- 这样部署到无人值守环境时，不会因为没人打开页面而自动停机
