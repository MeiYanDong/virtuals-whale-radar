# Phase 056 Runtime Autosell Control Plan

## 1. 目标

为管理员提供单项目的“自动卖出控制”页面，并让自动卖出执行器在发射过程中热加载配置。管理员可以在项目详情页直接调整税率窗口、冷却时间、事件回看窗口，以及多条自定义卖出规则；保存后不需要重启服务，后端在下一轮采样自动读取新版本。

## 2. 非目标

- 不在前端保存私钥。
- 不绕过现有广播门禁、execution RPC、active fuse、simulation 和 receipt 检查。
- 不做任意代码式策略编辑器；只开放经过白名单校验的条件组合式内盘卖出规则。
- 不允许普通用户修改自动卖出参数。

## 3. 运行时参数

- `enabled`：是否启用自动卖出运行时配置。
- `mode`：`simulate` 或 `broadcast`，前端不直接展示。
- `max_tax_rate`：卖出策略观察窗口，默认 `30%`。
- `cooldown_sec`：卖出冷却秒数，默认 `60`。
- `catch_up_events_sec`：大单事件回看窗口，默认 `120`。
- `custom_rules_json`：白名单条件组合式卖出规则配置。

## 4. 自定义卖出规则

自动卖出规则从固定四卡片升级为“条件组合器”：

- 一条规则的表达式为：当若干条件按 `AND` 或 `OR` 满足时，按原始仓位比例卖出。
- 第一版不支持括号嵌套；一条规则内部只能统一选择 `AND` 或 `OR`。
- 条件类型只开放三类：
  - 价格条件 `price`：代币价格达到阈值，单位支持 `USD` 或 `VIRTUAL`。
  - 大单条件 `large_buy`：最近回看窗口内出现单笔买入 `VIRTUAL` 或折算 `USD` 大于等于阈值。
  - 收益条件 `roi`：我方自身收益率达到阈值。
- 默认推荐规则：`收益率 >= 30% AND 单笔买入 >= 5000 VIRTUAL` 时卖出 `30%`。
- 旧规则 `limit_price / large_buy / high_roi / roi_and_large_buy` 仍可读取，并在保存时归一化为 `condition_group`。
- 多条规则独立生效；同一轮可能触发多条规则，卖出比例按规则增量累加，但总卖出比例不会超过 `100%`，实际卖出数量也不会超过当前钱包余额。
- 大单条件按 `rule_id + tx_hash` 去重，避免同一笔大单反复触发同一条规则。

推荐数据结构：

```json
{
  "id": "rule_roi_large_buy",
  "type": "condition_group",
  "enabled": true,
  "operator": "and",
  "sellPct": "30",
  "conditions": [
    { "id": "roi", "type": "roi", "roiPct": "30" },
    { "id": "large_buy", "type": "large_buy", "largeBuyThreshold": "5000", "largeBuyUnit": "v" }
  ]
}
```

## 5. 后端设计

- 新增 `launch_sell_runtime_configs` 表，按 `project_id` 保存当前项目自动卖出配置与版本号。
- 新增 `launch_sell_runtime_config_audit` 表，记录每次修改的 before/after。
- 新增管理员 API：
  - `GET /api/admin/projects/{project_id}/launch-sell-config`
  - `POST /api/admin/projects/{project_id}/launch-sell-config`
- API 静态校验：
  - 税率、收益率和卖出比例必须在可解释范围内。
  - 规则类型接受 `condition_group`，并兼容旧的 `limit_price / large_buy / high_roi / roi_and_large_buy`。
  - 条件类型只接受 `price / large_buy / roi`。
  - 每条规则必须至少包含一个条件。
  - 一条规则内部的逻辑只接受 `and / or`。
  - 卖出比例必须在 `0%` 到 `100%`。
  - 大单阈值必须大于 `0`，单位只接受 `VIRTUAL` 或 `USD`。
  - 限价阈值不能为负，单位只接受 `VIRTUAL` 或 `USD`。
  - 冷却时间不能小于 `0`。
  - 事件回看窗口必须大于 `0`。

## 6. 执行器设计

- `launch_sell_executor.py` 在循环中读取项目自动卖出运行时配置。
- 如果没有配置行，执行器默认视为未启用，不允许真实卖出，避免生产误触发。
- 如果配置存在但 `enabled=false`，执行器只记录 disabled 状态，不卖出。
- 如果配置 `mode=simulate`，广播模式执行器不真实卖出。
- 如果配置版本变化，执行器记录 `sell_config_reloaded`。
- 当 `strategy=custom_multi_sell` 或配置里存在 `custom_rules_json` 时，执行器使用 `CustomSellConfig` 与 `evaluate_custom_sell`。
- `evaluate_custom_sell` 支持 `condition_group` 的 `AND/OR` 判断，并继续兼容旧规则。
- 执行器每轮使用最新 sample、当前钱包余额、执行账本恢复的买入成本/已卖出比例、最近大单事件计算是否卖出。
- 配置解析异常或规则异常只会跳过无效规则，不应导致执行器崩溃；API 保存阶段会阻止无效配置写入 DB。

## 7. 前端设计

- 入口放在管理员项目详情页，紧跟“自动买入控制”之后。
- 模块名：`自动卖出控制`。
- 展示当前配置版本、是否已启用、已卖出目标、卖出次数、最近卖出时间和 active fuse 提示。
- 前端不展示 `trade_sent`、`mode`、`updated_reason` 等执行器/审计原生字段；这些只保留在后端和日志里。
- 提供三个用户可理解动作：
  - `恢复默认`：恢复默认税率窗口、冷却、回看窗口和默认规则。
  - `保存并启用`：内部保存为 broadcast 配置，但前端只表达业务动作。
  - `停用自动卖出`：危险操作，使用红色视觉强调。
- 字段标签和说明使用管理员能理解的业务表述，避免原生字段名。
- 前端改为“卖出规则构建器”：
  - 每条规则是一句业务表达：当条件满足时，卖出多少。
  - 用户可以给一条规则添加价格、大单、收益条件。
  - 用户可以选择这条规则内部是 `AND 全部满足` 或 `OR 任一满足`。
  - 默认只展示一条推荐规则：收益率 + 大单。

## 8. 验收标准

- 管理员能在项目详情页读取、修改并保存自动卖出参数。
- 保存后 API 返回递增版本号和审计记录。
- 执行器能从 DB 热加载配置，并改变后续卖出判断。
- 配置缺失、禁用或 simulate 模式不会真实广播卖出。
- 条件组合规则和旧规则兼容均有纯策略单元测试覆盖。
- 本地 Python 测试、前端 build/lint 通过。
- 本地执行器热加载探针能看到配置版本变化。
- 历史样本驱动真实 canary 能证明：运行中改卖出参数后，后续真实自动卖出使用新配置。

## 9. 历史样本真实广播验证（2026-05-18）

- `scripts/ops/historical_live_auto_trigger_canary.py` 使用 SR 历史样本流驱动 TDS internal-market 真实小额广播，验证自动卖出运行时改参不是只读模拟。
- sample `700` 写入并启用自动卖出后，执行器记录 `sell_config_reloaded`。
- sample `819` / tax `30%` 自动卖出本次 TDS 持仓，tx `0xce9d5637f82894ef2bfd2dc403664b6f143ba58b943ac3d0c7fc322fb8c47b0a`，receipt `0x1`。
- 测试使用预授权 token allowance，卖出执行时 `autoApproveEnabled=false`，避免把授权延迟混入卖出触发延迟。
