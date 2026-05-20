# Phase 061 Operator Profit Workflow

状态：当前主线。

本阶段目标不是继续做 Base 生态外部分发，而是让 Virtuals Whale Radar 成为我们自己在真实 Virtuals 发射窗口里赚钱的操作系统。所有新增工作按一个标准判断：能否提高下一次实盘胜率，或降低自动买入 / 自动卖出的执行失败率。

## 暂停项

- Base 生态上架、Base App、比赛提交暂停。
- 用户提前授权自动交易暂停。
- 普通用户自定义买卖单暂停。
- 欢迎页、登录页、Billing 的外部用户体验优化暂停。

已完成的 Base Account、OKX Wallet、Base USDC Billing 保留在主线里，但短期不继续投入。

## Operator 闭环

1. 项目发现：从 SignalHub / Virtuals 页面发现待发射项目，确认项目名称、SignalHub id、start time、token、internal pool、税率来源和是否纳入管理。
2. 发射前配置：确认项目在生产库中字段完整，runtime pause 为 false，realtime/backfill fresh，execution RPC 独立，active fuse 为空。
3. 资金与授权：确认 burner 钱包有足够 Base ETH、VIRTUAL balance、VIRTUAL buy allowance；卖出阶段只处理本系统买入后形成的仓位。
4. 策略参数：确认自动买入 runtime config、自动卖出 runtime config、单笔上限、单项目上限、卖出规则和大额买入回看窗口。
5. T-35 启动：用 systemd timer 启动 dry-run recorder、prewarm simulate、autobuy broadcast、autosell broadcast，并设置窗口后归档 timer。
6. 窗口中盯盘：只盯运行风险和交易事实，不做 UI 体验优化；重点是 sample 是否增长、ledger 是否写入、receipt 是否成功、fuse 是否触发。
7. 结束归档：输出 samples、events、execution ledger、fuses、summary、archive.db。
8. 复盘调参：用 archive 回放买入 / 卖出策略，记录真实 PnL 和下一次策略改动。

## 下一次 Live 项目操作清单

把 `<SYMBOL>`、`<START_AT_SERVER_LOCAL>` 和 `<BURNER_ADDRESS>` 替换为真实值。服务器时间按生产机本地时间填写。

### 1. 生产健康

```bash
systemctl is-active vwr@writer vwr@realtime vwr@backfill vwr-signalhub nginx
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8000/healthz
```

通过条件：

- 五个服务均为 `active`。
- 主程序 `/health` 返回 `ok=true`。
- `runtimePaused=false`。
- `queueSize=0` 或处于可解释的低水位。
- `pendingTx=0`，除非正在处理真实窗口。

### 2. Fuse 检查

```bash
cd /opt/virtuals-whale-radar
set -a
. /etc/virtuals-whale-radar/rpc.env
. /etc/virtuals-whale-radar/execution-rpc.env
set +a
.venv/bin/python scripts/ops/launch_execution_fuse.py --config config.json list
```

通过条件：

- 目标项目没有 active fuse。
- 如有历史 fuse，只能在确认根因和当前配置后手动 clear。

### 3. Execution RPC 压力观察

```bash
cd /opt/virtuals-whale-radar
set -a
. /etc/virtuals-whale-radar/rpc.env
. /etc/virtuals-whale-radar/execution-rpc.env
set +a
.venv/bin/python scripts/ops/launch_rpc_pressure_probe.py \
  --config config.json \
  --project <SYMBOL> \
  --owner <BURNER_ADDRESS> \
  --samples 20 \
  --output-json data/backtests/launch-rpc-pressure-<SYMBOL>.json
```

通过条件：

- `executionRpcSharedWithMain=false`。
- main RPC、execution RPC、market probe 没有连续失败。
- p90 延迟没有超过脚本阈值。

### 4. Readiness 检查

```bash
cd /opt/virtuals-whale-radar
set -a
. /etc/virtuals-whale-radar/rpc.env
. /etc/virtuals-whale-radar/execution-rpc.env
set +a
.venv/bin/python scripts/ops/launch_readiness_check.py \
  --config config.json \
  --project <SYMBOL> \
  --from-address <BURNER_ADDRESS> \
  --amount-v 25 \
  --amount-v 50 \
  --output-json data/backtests/launch-readiness-<SYMBOL>.json
```

通过条件：

- `ready=true`。
- `coreWorkflowReady=true`。
- `rpcSharedWithMain=false`。
- active fuse 数为 `0`。
- `25V` / `50V` simulation 绿灯。
- gas、balance、allowance 均满足预算。

### 5. Runtime 参数确认

在管理员项目页确认：

- 自动买入已启用，模式为 broadcast。
- 单笔上限符合本次预算。
- 单项目上限符合本次预算。
- 自动卖出已启用，模式为 broadcast。
- 卖出规则为当前生产规则或本次明确指定的规则。
- 大额买入事件回看窗口为 `120 秒`，除非本次复盘明确要求调整。

禁止在窗口中临时改不理解的参数。窗口中只能做明确的风险收敛动作：停用自动买入、停用自动卖出、clear 已确认无效的 fuse、或停止对应 systemd 服务。

### 6. 创建启动与归档 Timer

先 dry-run：

```bash
cd /opt/virtuals-whale-radar
.venv/bin/python scripts/ops/schedule_launch_services.py \
  --project <SYMBOL> \
  --start-at "<START_AT_SERVER_LOCAL>" \
  --json
```

确认 `serviceAt` 是发射前约 35 分钟，`archiveAt` 是窗口结束后，再 apply：

```bash
.venv/bin/python scripts/ops/schedule_launch_services.py \
  --project <SYMBOL> \
  --start-at "<START_AT_SERVER_LOCAL>" \
  --apply
```

通过条件：

- `vwr-launch-<symbol>-start.timer` active。
- `vwr-launch-<symbol>-archive.timer` active。
- 到点后会启动：
  - `vwr-launch-dryrun@<SYMBOL>.service`
  - `vwr-launch-prewarm@<SYMBOL>.service`
  - `vwr-launch-autobuy@<SYMBOL>.service`
  - `vwr-launch-autosell@<SYMBOL>.service`

### 7. 窗口中观察

只看这些事实：

- `data/execution/launch-samples-<SYMBOL>.jsonl` 是否持续增长。
- `data/execution/live-strategy-dry-run-<SYMBOL>.jsonl` 是否记录策略判断。
- `data/execution/launch-autobuy-<SYMBOL>.jsonl` 是否有 buy intent、simulation、broadcast、receipt。
- `data/execution/launch-autosell-<SYMBOL>.jsonl` 是否有 position、sell decision、approve、sell receipt。
- `launch_execution_fuses` 是否出现 active fuse。
- 主 `/health` 是否仍为 ok，queue/pending 是否异常堆积。

窗口中不优化文案、不调欢迎页、不修 Billing，除非这些问题阻塞实盘交易。

### 8. 结束归档

归档 timer 会自动执行。若需要手动补归档：

```bash
cd /opt/virtuals-whale-radar
.venv/bin/python scripts/ops/archive_launch_project.py \
  --config config.json \
  --project <SYMBOL> \
  --output-dir data/launch-archives \
  --archive-name <YYYY-MM-DD>-<SYMBOL>-manual \
  --overwrite
```

通过条件：

- `summary.json` 存在。
- `samples.jsonl` 非空。
- `events.jsonl` 非空或有合理解释。
- `execution-ledger.jsonl` 包含本次执行事实。
- `fuses.jsonl` 记录本次 fuse 状态。
- `archive.db` 存在。

### 9. 回放复盘

```bash
python3 scripts/ops/recalc_dynamic_buy_strategy.py \
  --report data/launch-archives/<ARCHIVE>/summary.json \
  --output-json data/backtests/<SYMBOL>-buy-recalc.json \
  --output-md docs/phases/phase-061-<symbol>-buy-recalc.md

python3 scripts/ops/recalc_dual_sell_strategy.py \
  --report data/launch-archives/<ARCHIVE>/summary.json \
  --rule dual_roi_large_buy_sell \
  --output-json data/backtests/<SYMBOL>-sell-recalc.json \
  --output-md docs/phases/phase-061-<symbol>-sell-recalc.md
```

复盘只回答一个问题：下一次真实窗口应该怎么提高胜率或降低失败率。

## 一页复盘报告模板

每个真实 live 项目结束后写一页报告，建议放到 `docs/phases/phase-061-<symbol>-live-review.md`。

```markdown
# <SYMBOL> Live Review

## 结论

- 是否赚钱：
- 最终 PnL：
- 是否符合预期：
- 下一次要改什么：

## 发射前

- 项目：
- start time：
- burner：
- buy budget：
- sell rule：
- readiness：
- execution RPC：
- active fuse：

## 买入事实

| 时间 | 触发原因 | 税率 | 含税 FDV | 金额 V | tx | receipt |
| --- | --- | --- | --- | --- | --- | --- |

## 卖出事实

| 时间 | 触发原因 | 收益率 | 大额买入 | 卖出比例 | tx | receipt |
| --- | --- | --- | --- | --- | --- | --- |

## 风险与失败

- RPC：
- nonce / gas：
- allowance / balance：
- receipt：
- fuse：
- 数据延迟：

## 策略复盘

- 本次正确判断：
- 本次错误判断：
- 如果重放 archive，会怎么改买入：
- 如果重放 archive，会怎么改卖出：

## 下一次动作

1.
2.
3.
```

## 当前已知缺口

- 2026-05-20 生产机已完成一次 `launch_rpc_pressure_probe.py`，确认 execution RPC 和 main RPC 不共享；后续仍需在每个真实窗口前复跑。
- 下一次真实 live 项目必须用 `schedule_launch_services.py` 创建 timer，而不是手工临时启动四个服务。
- 当前候选记录见 `docs/phases/phase-061-live-candidates-2026-05-20.md`；`MTR` 已创建只读 `dryrun,prewarm` timer，发射前 direct buy 仍 revert，需要窗口前复跑 readiness。
- 归档必须成为每次窗口的默认产物；没有 archive 的实盘窗口，不算完成闭环。
- 页面优化优先级低于执行失败率、真实 PnL 和复盘质量。
