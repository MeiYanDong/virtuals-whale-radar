# Phase 055 Runtime Strategy Control Plan

## 1. 目标

为管理员提供单项目的“自动买入控制”页面。在发射过程中，如果人工判断项目热度变化，可以把基础买入金额从 `25 VIRTUAL` 调整为 `100 VIRTUAL`，把抄底买入金额从 `50 VIRTUAL` 调整为 `200 VIRTUAL`，并让自动买入执行器无需重启即可读取新参数。

## 2. 非目标

- 不在前端保存私钥。
- 不绕过现有广播门禁、独立 execution RPC、active fuse 和 receipt 检查。
- 不做完整策略编辑器；第一版只开放生产必要参数。
- 不允许普通用户修改自动买入参数。

## 3. 第一版参数

- `enabled`：是否启用运行时配置。
- `mode`：`simulate` 或 `broadcast`。
- `base_buy_v`：基础买入 VIRTUAL 数量，默认 `25`。
- `dip_buy_v`：抄底买入 VIRTUAL 数量，默认 `50`。
- `dip_from_own_cost_pct`：低于我方加权成本多少百分比触发抄底，默认 `20`。
- `flat_pause_pct`：相邻税率档横盘暂停阈值，默认 `10`。
- `max_buy_v`：单笔最大买入上限。
- `max_project_v`：单项目总预算上限。
- `updated_reason`：人工修改原因，进入审计日志。

## 4. 后端设计

- 新增 `launch_strategy_runtime_configs` 表，按 `project_id` 保存当前运行配置与版本号。
- 新增 `launch_strategy_runtime_config_audit` 表，记录每次修改的 before/after。
- 新增管理员 API：
  - `GET /api/admin/projects/{project_id}/launch-strategy-config`
  - `POST /api/admin/projects/{project_id}/launch-strategy-config`
- API 静态校验：
  - `base_buy_v > 0`
  - `dip_buy_v > 0`
  - `max_buy_v > 0`
  - `max_project_v > 0`
  - `base_buy_v <= max_buy_v`
  - `dip_buy_v <= max_buy_v`
  - `max_project_v >= 当前已发送买入 V`

## 5. 执行器设计

- `launch_prewarm_executor.py` 在循环中读取项目运行时配置。
- 如果没有配置行，沿用 CLI/systemd 默认值，保持向后兼容。
- 如果配置存在但 `enabled=false`，执行器只记录 disabled 状态，不发出 BuyIntent。
- 如果配置 `mode=simulate`，广播模式执行器不真实买入。
- 如果配置版本变化，执行器记录 `strategy_config_reloaded`。
- 运行时配置只能收窄或调整策略金额；真实广播仍必须满足原有 `--enable-broadcast`、`VWR_ENABLE_AUTO_BUY_BROADCAST=1`、独立 execution RPC 和 active fuse 检查。

## 6. 前端设计

- 入口放在管理员项目详情页，不放全局 Settings。
- 模块名：`自动买入控制`。
- 展示当前配置版本、是否已启用、基础买入、抄底买入、单笔上限、项目预算、抄底阈值、横盘跳过和已买入 V。
- 前端不展示 `trade_sent`、`mode`、`updated_reason` 等执行器/审计原生字段；这些只保留在后端和日志里。
- 金额字段在字段内标注单位 `VIRTUAL`，百分比字段在字段内标注 `%`，不再单独占用一行说明。
- `抄底阈值` 和 `横盘跳过` 需要使用和成本位一致的信息图标解释：
  - `抄底阈值`：当前含税估算 FDV 低于我方历史加权买入 FDV 该比例以上时，使用抄底买入金额。
- `横盘跳过`：某税率档买入后，下一相邻税率档含税估算 FDV 相对上一买点变化不超过该比例时，跳过这一档，下一档重新判断。
- 当前端调整基础买入或抄底买入时，如果金额高于单笔上限，自动把单笔上限抬到对应金额，避免把 `dipBuyV/maxBuyV` 这类内部字段错误暴露给管理员。
- 参数卡片、预设按钮和输入项需要有明确 hover / focus 反馈，方便管理员在发射窗口内快速确认可操作区域。
- 提供三个用户可理解动作：
  - `恢复默认`：恢复 `25/50/50/150` 与 `20/10` 阈值。
  - `保存并启用`：内部保存为 broadcast 配置，但前端只表达业务动作。
  - `停用自动买入`：危险操作，使用红色视觉强调。
- 当单笔金额明显放大时，前端提示二次确认；后端仍以静态风控为准。

## 7. 验收标准

- 管理员能在项目详情页读取、修改并保存自动买入参数。
- 保存后 API 返回递增版本号和审计记录。
- 执行器能从 DB 热加载配置并改变后续 BuyIntent 金额。
- 配置禁用或 simulate 模式不会真实广播。
- 本地 Python 测试、前端 build/lint 通过。

## 8. 生产探针结果

- 2026-05-16 在生产管理员页面 `/admin/projects/15?project=ROO` 真实输入并保存自动买入参数，后端 POST 返回 `200`。
- 保存后 API 回读 `enabled=true / mode=broadcast / baseBuyV=0.002000 / dipBuyV=0.003000`。
- 随后通过页面执行“停用自动买入”，并清理 ROO 探针配置行，避免 ended 项目残留启用配置。
- 临时写入 `baseBuyV=0.004 / dipBuyV=0.005` 后启动只读执行器，日志记录 `hasOverride=true / version=1 / mode=broadcast`，证明执行器能热读取生产 DB 配置。
- ROO 当前 `status=ended`，执行器正确输出 `not_live` 且 `tradeSent=false`，没有伪造内盘买入。
