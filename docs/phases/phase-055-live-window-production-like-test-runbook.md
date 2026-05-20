# Phase 055 Live Window Production-Like Test Runbook

## 1. 目标

验证自动买入在 `live` 发射窗口内的真实运行方式，覆盖两类买入：

- 普通买入策略：`LIVE + 税率 <= 95% + 榜单 V >= 5,000 + 有效榜单/成本样本 + 含税 FDV <= 榜单成本`。
- 独立含税估算 FDV 限价单：`LIVE + 当前含税估算 FDV <= 订单限价`。

目标不是证明某个历史项目收益，而是证明：

- 前端创建、删除、更新配置后，后端 DB 立即保存。
- 执行器每个 tick 热读取最新 DB 状态，不需要重启。
- 普通买入和限价单都能从样本流自动触发，不靠手动调用买入脚本。
- 真实广播前的安全门禁、独立 execution RPC、active fuse、simulation、签名、receipt/账本路径都保持生产一致。

## 2. 测试分层

### L1: API/DB 写入验证

验证对象：

- `POST /api/admin/projects/{project_id}/launch-strategy-config`
- `POST /api/admin/projects/{project_id}/launch-fdv-limit-orders`
- `launch_strategy_runtime_configs`
- `launch_fdv_limit_orders`

通过标准：

- 新增限价单后，GET 立即返回新订单。
- 修改限价 FDV、买入数量、参与触发状态后，GET 立即返回新值。
- 删除未执行订单后，该订单变为 `canceled / enabled=0`，不再参与触发。
- 已 `triggering / broadcast_sent / filled` 的订单不会被普通保存误删。

### L2: 本地 paper live 窗口回放

脚本：

```bash
.venv/bin/python scripts/ops/runtime_control_launch_simulator.py \
  --config config.json \
  --project TDS \
  --speed 100 \
  --output-jsonl data/execution/runtime-control-launch-sim-TDS-100x.jsonl \
  --summary-json data/execution/runtime-control-launch-sim-TDS-100x-summary.json
```

生产相似点：

- 读取真实 SQLite 配置。
- 每个 tick 重新读取 `launch_strategy_runtime_configs`。
- 每个 tick 重新读取 `launch_fdv_limit_orders`。
- 使用生产 `DynamicAfter1StrategyEvaluator`。
- 使用生产限价单 eligibility 逻辑。

差异：

- 不签名。
- 不广播。
- 不写 `launch_execution_ledger`。

通过标准：

- 普通策略输出 `paper_buy_intent`。
- 限价单输出 `paper_fdv_limit_order_intent`。
- 修改限价单后，下一 tick 使用新限价和新买入数量。
- 删除限价单后，下一 tick 不再输出该订单意图。
- 项目预算耗尽后，普通买入和限价单都被 paper risk cap 阻断。

门禁说明：

- `runtime_control_launch_simulator.py` 是 paper-only，不会签名或广播。
- 但为了贴近生产，它仍遵守运行时配置门禁：`enabled=true` 且 `mode=broadcast` 时才评估普通买入和限价单。
- 如果只想验证“关闭后不触发”，保持 `enabled=false` 或 `mode=simulate`。
- 如果要验证“前端改参后下一 tick 热读”，应临时切到 `enabled=true / mode=broadcast`，跑完立即恢复。

手工热读验证建议：

- 用 `--speed 20` 跑回放，给前端留出操作时间。
- 回放运行中，在网页新增、暂停、修改、删除限价单。
- 观察 JSONL 的下一批 tick 是否出现对应变化。
- 纯自动烟测用 `--speed 100`，完整窗口约一分钟跑完。

### L3: prewarm simulate

脚本：

```bash
.venv/bin/python scripts/ops/launch_prewarm_executor.py \
  --config config.json \
  --project TDS \
  --mode simulate \
  --once
```

生产相似点：

- 走生产执行器。
- 构造真实交易。
- 调用 execution RPC。
- 执行 `eth_call / estimateGas / balance / allowance / nonce` 检查。
- 读取限价单并判断是否 eligible。

差异：

- 不读取私钥。
- 不签名。
- 不广播。

通过标准：

- `rpcSharedWithMain=false`。
- 触发条件满足时，普通策略或限价单进入 simulation 绿灯或明确 readiness 阻断。
- readiness 阻断不能误写成已买入。

### L4: sign-ready

用途：

- 验证 burner 私钥、from 地址、nonce、fee、calldata、deadline、签名摘要。
- 仍然不广播。

要求：

- 只允许 burner wallet。
- 私钥只能来自 `VWR_BURNER_PRIVATE_KEY` 或 root-only secret file。
- 禁止打印或写入 raw private key / raw signed tx。

### L5: 小额真实 broadcast canary

用途：

- 最接近生产 live 窗口。
- 历史样本流自动驱动触发，当前仍可交易的 internal market 项目负责真实成交。

生产相似点：

- 自动触发，不手动调用买入。
- 前端/API 写入运行时配置。
- 执行器热读配置。
- 真实签名、广播、receipt、账本。
- 独立 execution RPC。

差异：

- 历史样本的价格不等于当前链上成交价。
- 交易金额使用极小值，例如 `0.01V` 或 `0.1V`。

通过标准：

- 普通买入真实小额 receipt 成功。
- 限价单真实小额 receipt 成功。
- 多个限价单同 tick 满足时，按限价从高到低连续广播，nonce 递增正确。
- 已广播/已成交订单后续不重复触发。
- 测试后恢复 runtime config、清理/暂停测试订单、检查 active fuse 为 0。

## 3. 限价单专项矩阵

| 场景 | 期望 |
| --- | --- |
| 项目非 LIVE | 不触发 |
| FDV 高于限价 | 不触发，订单保持 pending |
| FDV 等于限价 | 触发 |
| FDV 低于限价 | 触发 |
| 订单暂停触发 | 不触发 |
| 前端修改限价 | 下一 tick 用新限价 |
| 前端修改买入数量 | 下一 tick 用新数量 |
| 前端删除订单 | 下一 tick 不再参与触发 |
| 多单同时满足 | 按限价从高到低发送 |
| 自动买入总开关关闭 | 限价单也不广播 |
| 余额或授权不足 | 记录 readiness 阻断或可重试，不误判成交 |
| 已广播/已成交订单 | 不被普通保存误删，不重复触发 |

## 4. 生产前最低验收

上线前必须同时满足：

- `npm run lint && npm run build` 通过。
- `test_launch_execution_pipeline.py` 通过。
- `test_launch_prewarm_executor.py` 通过。
- `runtime_control_launch_simulator.py` 通过普通买入和限价单 paper 回放。
- `launch_prewarm_executor.py --mode simulate --once` 在目标项目上可运行。
- execution RPC 与主采集 RPC 分离，日志显示 `rpcSharedWithMain=false`。
- active fuse 为空。
- burner wallet 的 VIRTUAL allowance 和余额符合测试金额。
- 真实 broadcast canary 必须使用小额，且测试后恢复配置。

## 5. 结论口径

- L2 通过：证明前端/API -> DB -> 执行器热读 -> 策略判断链路成立。
- L3/L4 通过：证明交易构造、模拟、签名准备接近生产。
- L5 通过：才能说普通买入或限价单已经完成最接近生产 live 窗口的验证。
- 任何单层通过都不能单独等同于“生产万无一失”。
