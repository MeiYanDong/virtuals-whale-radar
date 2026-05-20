# Phase 061 Live Candidates - 2026-05-20

状态：MTR 已进入只读观察准备，未启动真实交易。

本记录用于 Phase 061 自用实盘盈利闭环。目标不是做外部用户体验，而是找到下一次可用于完整 runbook 的真实 Virtuals 发射窗口。

## 候选来源

来源：生产 SignalHub upcoming feed。

生产机时间：`2026-05-20 10:27:51 CST +0800`。

| 项目 | 名称 | SignalHub id | 发射时间 | token | internal pool | 评分 | 风险 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PROFIT | Agentic Hedge Fund | 72112 | 2026-05-20 21:00:15 CST | `0x169fa1e32EFa517068390cfCB81ad8FcDEd0c51A` | `0xe60f9b9727e073afad0949118a13241313d8da8a` | C / 58 | medium | `contract_ready=true`，`BONDING_V5`，`antiSniperTaxType=2` |
| MTR | Motius Robotics | 75239 | 2026-05-21 21:28:57 CST | `0xEB30D8AbEaF98F7e87C9ab19334C7C8B5d8be0DE` | `0x297bff1ef6c53b28f54221dda991fe8846539e6e` | C / 58 | medium | `contract_ready=true`，`BONDING_V5`，`antiSniperTaxType=2`，robotics，airdrop `0.25` |

## 非广播预检

已在生产机使用 `scripts/ops/prewarmed_buy_canary.py` 进行非广播模拟：

- 未传 `--broadcast`。
- `broadcastRequested=false`。
- `broadcasted=false`。
- `tradeSent=false`。
- 使用独立 execution RPC：`executionRpcSource=VWR_EXEC_HTTP_RPC_URL`，`rpcSharedWithMain=false`。

### 25 V 模拟

输出文件：

- `data/backtests/phase-061-PROFIT-prewarmed-buy-sim-20260520.json`
- `data/backtests/phase-061-MTR-prewarmed-buy-sim-20260520.json`

结果：

| 项目 | simulation | 余额 | VIRTUAL 授权 | eth_call / estimateGas | 判断 |
| --- | --- | --- | --- | --- | --- |
| PROFIT | not green | 约 `70.67 V`，满足 25 V | 约 `9.93 V`，不满足 25 V | revert `0xd4181deb` | 还不能买；25 V 预算还需要提前授权 |
| MTR | not green | 约 `70.67 V`，满足 25 V | 约 `9.93 V`，不满足 25 V | revert `0xd4181deb` | 还不能买；25 V 预算还需要提前授权 |

### 5 V 模拟

输出文件：

- `data/backtests/phase-061-PROFIT-prewarmed-buy-sim-5v-20260520.json`
- `data/backtests/phase-061-MTR-prewarmed-buy-sim-5v-20260520.json`

结果：

| 项目 | simulation | VIRTUAL 授权 | eth_call / estimateGas | 判断 |
| --- | --- | --- | --- | --- |
| PROFIT | not green | 满足 5 V | revert `0xd4181deb` | 失败主因不是授权额度，推断为尚未到可交易状态 |
| MTR | not green | 满足 5 V | revert `0xd4181deb` | 失败主因不是授权额度，推断为尚未到可交易状态 |

## 排程预览

只做 dry-run 预览，未 `--apply`。

| 项目 | 发射时间 | T-35 启动 | 归档时间 | 预览服务 |
| --- | --- | --- | --- | --- |
| PROFIT | 2026-05-20 21:00:15 CST | 2026-05-20 20:25:15 CST | 2026-05-20 22:49:15 CST | `dryrun,prewarm` |
| MTR | 2026-05-21 21:28:57 CST | 2026-05-21 20:53:57 CST | 2026-05-21 23:17:57 CST | `dryrun,prewarm` |

## MTR 只读观察准备

2026-05-20 已在生产机执行以下准备动作：

- 将 `MTR` 加入 `managed_projects`，生产 id 为 `16`。
- `is_watched=1`，`collect_enabled=1`，`backfill_enabled=1`，`status=scheduled`，`source=signalhub`。
- 创建 `vwr-launch-mtr-start.timer`，触发时间 `2026-05-21 20:53:57 CST`。
- 创建 `vwr-launch-mtr-archive.timer`，触发时间 `2026-05-21 23:17:57 CST`。
- start unit 仅包含 `vwr-launch-dryrun@MTR.service` 与 `vwr-launch-prewarm@MTR.service`。
- 未创建本次 `autobuy/autosell` 启动链路；四个 launch service 当前均为 `inactive`。

生产健康检查：

- `vwr@writer`、`vwr@realtime`、`vwr@backfill`、`vwr-signalhub`、`nginx` 均为 `active`。
- `/health ok=true`，`queueSize=0`，`pendingTx=0`。

注意：`schedule_launch_services.py` 会安装四个模板文件，但本次 `vwr-launch-mtr-start.service` 的 `ExecStart` 只启动 `dryrun` 和 `prewarm` 两个服务。

## 2026-05-20 11:15 CST 复查

本次复查仍为只读，不签名、不广播。

生产健康：

- 服务器时间：`2026-05-20 11:14:57 CST +0800`。
- `vwr@writer`、`vwr@realtime`、`vwr@backfill`、`vwr-signalhub`、`nginx` 均为 `active`。
- `/health ok=true`，`queueSize=0`，`pendingTx=0`，`runtimePaused=false`。
- SignalHub `/healthz` 返回 `{"status":"ok"}`。

MTR timer：

- `vwr-launch-mtr-start.timer` active，触发时间仍为 `2026-05-21 20:53:57 CST`。
- `vwr-launch-mtr-archive.timer` active，触发时间仍为 `2026-05-21 23:17:57 CST`。
- `vwr-launch-mtr-start.service` 仍只启动 `vwr-launch-dryrun@MTR.service` 和 `vwr-launch-prewarm@MTR.service`。
- `vwr-launch-dryrun@MTR`、`vwr-launch-prewarm@MTR`、`vwr-launch-autobuy@MTR`、`vwr-launch-autosell@MTR` 当前均为 `inactive`。

Fuse：

- 当前没有 MTR active fuse。
- 历史 ROO fuse 已清除，不影响 MTR。

Execution RPC 压力观察：

- 输出文件：`data/backtests/phase-061-MTR-rpc-pressure-20260520-111537.json`。
- `executionRpcSharedWithMain=false`。
- `executionRpcSource=VWR_EXEC_HTTP_RPC_URL`。
- `mainP90Ms=146.8`，`executionP90Ms=143.5`，`marketP90Ms=152.5`。
- 结论：RPC 侧绿灯。

Readiness：

- 输出文件：`data/backtests/phase-061-MTR-readiness-20260520-111537.json`。
- `ready=false`，因为 MTR 当前仍为 `scheduled`，direct buy 仍未到可交易状态。
- `coreWorkflowReady=true`，`eventQueueSize=0`，`activeFuseCount=0`，`rpcSharedWithMain=false`。
- 钱包 Base ETH 约 `0.0003959 ETH`，足够发送 approve gas。
- 钱包 VIRTUAL 余额约 `70.67 V`。
- 当前 VIRTUAL buy allowance 约 `9.93 V`。
- `5V`：allowance / balance 足够，但 `ethCall` 与 `estimateGas` 仍 revert `0xd4181deb`。
- `25V` / `50V`：allowance 不足，且 `ethCall` 与 `estimateGas` 仍 revert `0xd4181deb`。

复查结论：

- MTR 现在仍应保持只读演练，不应提前升级真钱广播。
- 如果后续要按 `25V` 或 `50V` 买入，需要在发射前完成 VIRTUAL buy allowance 提升。
- T-35 到 T-5 之间必须再次复跑 readiness；只有项目状态进入可交易窗口且 simulation 变绿，才讨论是否升级 `autobuy/autosell`。

## 当前判断

1. `PROFIT` 是今天的即时候选，但时间更紧，且只有 C / medium。
2. `MTR` 发射在明天，准备时间更充分，也更适合作为第一次完整 Phase 061 runbook 演练。
3. 两个项目在发射前的 direct buy simulation 目前都会 revert；这不等于项目不可用，更可能是还没到可交易窗口。需要在 T-35 到 T-5 重新跑 readiness。
4. 如果实盘预算按 25 V 或以上执行，必须提前提高 VIRTUAL buy allowance；当前授权约 9.93 V，只够小额测试。
5. 真实自动买入 / 自动卖出 timer 不应默认创建。必须先明确本次是否真钱参与、预算、买入上限、卖出规则和是否允许广播。

## 下一步

- 默认建议：用 `MTR` 做 Phase 061 第一次完整 runbook 演练；`PROFIT` 只做观察或 dryrun。
- 已执行的安全动作：`MTR` 已加入管理 / watch，并创建 `dryrun,prewarm` 的系统 timer 与窗口后归档 timer。
- 需要明确确认后才能执行的动作：VIRTUAL 授权广播、`autobuy,autosell` timer、任何真实买入或卖出广播。
