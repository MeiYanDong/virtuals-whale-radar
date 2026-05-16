# Phase 056 Runtime Autosell Control Plan

## 1. 目标

为管理员提供单项目的“自动卖出控制”页面，并让自动卖出执行器在发射过程中热加载配置。管理员可以在项目详情页直接调整税率窗口、收益率档位、大单档位、卖出比例、冷却时间和事件回看窗口，不需要重启服务。

## 2. 非目标

- 不在前端保存私钥。
- 不绕过现有广播门禁、execution RPC、active fuse、simulation 和 receipt 检查。
- 不做通用策略编辑器；第一版只开放当前已冻结的双条件卖出策略参数。
- 不允许普通用户修改自动卖出参数。

## 3. 第一版参数

- `enabled`：是否启用自动卖出运行时配置。
- `mode`：`simulate` 或 `broadcast`，前端不直接展示。
- `max_tax_rate`：卖出策略观察窗口，默认 `30%`。
- `roi_low_pct`：收益率一档，默认 `30%`。
- `roi_high_pct`：收益率二档，默认 `50%`。
- `large_buy_low_v`：大单一档，默认 `5000 VIRTUAL`。
- `large_buy_high_v`：大单二档，默认 `8000 VIRTUAL`。
- `sell_low_pct`：卖出一档，默认 `30%`。
- `sell_high_pct`：卖出二档，默认 `50%`。
- `cooldown_sec`：卖出冷却秒数，默认 `60`。
- `catch_up_events_sec`：大单事件回看窗口，默认 `120`。

## 4. 后端设计

- 新增 `launch_sell_runtime_configs` 表，按 `project_id` 保存当前项目自动卖出配置与版本号。
- 新增 `launch_sell_runtime_config_audit` 表，记录每次修改的 before/after。
- 新增管理员 API：
  - `GET /api/admin/projects/{project_id}/launch-sell-config`
  - `POST /api/admin/projects/{project_id}/launch-sell-config`
- API 静态校验：
  - 税率、收益率和卖出比例必须在可解释范围内。
  - 二档阈值不能低于一档阈值。
  - 大单阈值必须大于 `0`。
  - 冷却时间不能小于 `0`。
  - 事件回看窗口必须大于 `0`。

## 5. 执行器设计

- `launch_sell_executor.py` 在循环中读取项目自动卖出运行时配置。
- 如果没有配置行，执行器默认视为未启用，不允许真实卖出，避免生产误触发。
- 如果配置存在但 `enabled=false`，执行器只记录 disabled 状态，不卖出。
- 如果配置 `mode=simulate`，广播模式执行器不真实卖出。
- 如果配置版本变化，执行器记录 `sell_config_reloaded`。
- 执行器使用最新配置生成 `DualSellConfig`，并同步调整 CLI 等效参数，包括税率窗口、冷却时间和事件回看窗口。

## 6. 前端设计

- 入口放在管理员项目详情页，紧跟“自动买入控制”之后。
- 模块名：`自动卖出控制`。
- 展示当前配置版本、是否已启用、已卖出目标、卖出次数、最近卖出时间和 active fuse 提示。
- 前端不展示 `trade_sent`、`mode`、`updated_reason` 等执行器/审计原生字段；这些只保留在后端和日志里。
- 提供三个用户可理解动作：
  - `恢复默认`：恢复 `30/50` 收益率、`5000/8000` 大单、`30/50` 卖出比例、`60s` 冷却和 `120s` 回看窗口。
  - `保存并启用`：内部保存为 broadcast 配置，但前端只表达业务动作。
  - `停用自动卖出`：危险操作，使用红色视觉强调。
- 字段标签和说明使用管理员能理解的业务表述，避免原生字段名。

## 7. 验收标准

- 管理员能在项目详情页读取、修改并保存自动卖出参数。
- 保存后 API 返回递增版本号和审计记录。
- 执行器能从 DB 热加载配置，并改变后续卖出判断。
- 配置缺失、禁用或 simulate 模式不会真实广播卖出。
- 本地 Python 测试、前端 build/lint 通过。
- 本地执行器热加载探针能看到配置版本变化。
