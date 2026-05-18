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
- 展示当前配置版本、是否已启用、买入触发条件、基础买入、抄底买入、单笔上限、项目预算、抄底阈值、横盘跳过和已买入 V。
- 前端重构为“买入策略卡”，而不是普通参数表：
  - `买入触发条件`：只读展示，不支持前端修改，不向后端提交新字段。
  - `买入金额`：编辑基础买入和抄底买入。
  - `节奏保护`：编辑横盘跳过阈值，同时明确当前策略为每个税率档最多买入一次。
  - `抄底放大`：编辑低于我方成本多少百分比后放大买入。
  - `风险上限`：编辑单笔上限和项目预算。
- 买入触发条件按当前后端策略事实展示：
  - `LIVE 中`
  - `税率 ≤ 95%`
  - `榜单 V ≥ 5,000`
  - `有效榜单 20 人 / 5 个成本样本`
  - `含税 FDV ≤ 榜单成本`
- `有效榜单 20 人 / 5 个成本样本` 不是重复条件：
  - `榜单人数` 表示进入大户榜单的地址广度。
  - `成本样本` 表示经过团队/初始化过滤后，能参与榜单成本计算的有效地址数。
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
- 历史样本驱动真实 canary 能证明：运行中改买入参数后，后续真实自动买入使用新值。

## 8. 生产探针结果

- 2026-05-16 在生产管理员页面 `/admin/projects/15?project=ROO` 真实输入并保存自动买入参数，后端 POST 返回 `200`。
- 保存后 API 回读 `enabled=true / mode=broadcast / baseBuyV=0.002000 / dipBuyV=0.003000`。
- 随后通过页面执行“停用自动买入”，并清理 ROO 探针配置行，避免 ended 项目残留启用配置。
- 临时写入 `baseBuyV=0.004 / dipBuyV=0.005` 后启动只读执行器，日志记录 `hasOverride=true / version=1 / mode=broadcast`，证明执行器能热读取生产 DB 配置。
- ROO 当前 `status=ended`，执行器正确输出 `not_live` 且 `tradeSent=false`，没有伪造内盘买入。

## 9. 本地发射模拟验证（2026-05-18）

- 新增本地只读脚本 `scripts/ops/runtime_control_launch_simulator.py`，用于验证“前端保存参数 -> DB 版本变化 -> 执行器热读 -> 后续触发条件使用新值”的完整链路。
- 该脚本只做 paper replay：不签名、不广播、不写 `launch_execution_ledger`；适合在本地用小额参数快速模拟完整发射窗口。
- 前端在 `/admin/projects/1?project=TDS` 输入并保存：
  - 基础买入 `0.1 VIRTUAL`
  - 抄底买入 `0.2 VIRTUAL`
  - 单笔上限 `0.2 VIRTUAL`
  - 项目预算 `0.6 VIRTUAL`
  - 抄底阈值 `20%`
  - 横盘跳过 `10%`
- 保存后后端回读 `enabled=true / mode=broadcast / version=22`，证明网页操作已传导到后端运行时配置。
- 100x 完整窗口模拟命令：
  - `.venv/bin/python scripts/ops/runtime_control_launch_simulator.py --config config.json --project TDS --speed 100 --output-jsonl data/execution/runtime-control-launch-sim-TDS-100x-20260518.jsonl --summary-json data/execution/runtime-control-launch-sim-TDS-100x-20260518-summary.json`
- 验证结果：
  - 99 个税率 tick 在约 1 分钟内跑完。
  - 执行器按前端新值产生 4 次 paper buy intent：税率 `95/93/92/90`，买入金额 `0.1/0.2/0.1/0.2 VIRTUAL`。
  - 税率 `94/91` 因相邻税率档 FDV 变化小于等于 `10%` 被跳过。
  - 累计 paper 买入达到 `0.6 VIRTUAL` 后，后续 89 次意图均被项目预算风控拦截。
  - 全程 `paperOnly=true / tradeSent=false`。
- 模拟完成后通过本地 API 停用配置，回读 `enabled=false / mode=simulate / version=23`，避免测试启用状态残留。
- 倍速使用建议：
  - 全窗口烟测使用 `100x`，99 分钟窗口约 1 分钟跑完。
  - 如果需要人工在前端中途修改参数并观察下一 tick 热加载，使用 `20x`，或在后续脚本里加入暂停检查点；纯 `100x` 太快，不适合手工改参。

## 10. 历史样本真实广播验证（2026-05-18）

- `scripts/ops/historical_live_auto_trigger_canary.py` 使用 SR 历史样本流驱动 TDS internal-market 真实小额广播，验证自动买入运行时改参不是只读模拟。
- sample `30` 写入买入参数 `0.005 -> 0.01 VIRTUAL` 后，执行器记录 `strategy_config_reloaded`。
- sample `55` / tax `95%` 自动买入使用新值 `0.01 VIRTUAL`，tx `0x541481388328fb7a8181b05ed749518c0fffc605b05badada5b5a8db584062e5`，receipt `0x1`。
