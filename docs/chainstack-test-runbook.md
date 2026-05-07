# Chainstack-only Test Runbook

本文件把当前项目已有测试能力整合成一套可复用的测试顺序。目标是在 ANKR / Alchemy / public RPC 额度紧张时，只使用 Chainstack 尽量提前发现真实发射风险。

## 1. 原则

- 默认只使用 Chainstack：
  - `CHAINSTACK_BASE_HTTP_RPC_URL`
  - `CHAINSTACK_BASE_WS_RPC_URL`
- 不把 RPC endpoint token 写入 Git、文档或终端截图。
- 优先使用隔离库测试；只有明确进入修复流程时才写生产库。
- 对 replay 结果优先比较 V-native 指标，避免被当前 `VIRTUAL/USD` 折算价格干扰：
  - `tokenPriceV`
  - `含税 FDV(V)`
  - `榜单成本 FDV(V)`
- 真实发射前的核心判断不是单个页面能不能打开，而是整条链路是否闭环：

```text
SignalHub 身份识别
-> Virtuals launchInfo / 税率配置
-> Chainstack logs / receipt / historical block / historical getReserves
-> 事件解析与入库
-> market payload
-> overview / leaderboard / 成本位
-> 前端展示
-> 结束后完整性审计
```

## 2. 当前已有测试能力

| 类别 | 入口 | 是否写生产库 | 用途 |
| --- | --- | --- | --- |
| 基础构建 | `npm run build` | 否 | 前端 TypeScript + Vite 构建检查 |
| 前端 lint | `npm run lint` | 否 | 前端静态检查 |
| 运维脚本语法 | `bash -n scripts/ops/*.sh` | 否 | 防止部署脚本语法错误 |
| 生产健康检查 | `curl /healthz`、`curl /health`、`systemctl is-active` | 否 | 确认当前服务状态 |
| Chainstack RPC smoke | `eth_blockNumber` / `eth_getBlockByNumber` / `eth_getLogs` / receipt / WSS | 否 | 确认 Chainstack 当前节点能力 |
| 原生发射 replay | `scripts/ops/native_launch_replay.py` | 否，默认隔离 SQLite | 最接近生产的模拟真实发射测试 |
| replay 前端可视化 | `native_launch_replay.py --serve --manual` | 否，默认隔离 SQLite | 在前端手动观察含税 FDV / 成本位刷新 |
| 项目窗口审计 | `scripts/ops/audit_project_window.py` | 否，默认只读 | 项目结束后发现漏扫、漏解析、dead-letter |
| 缺口 tx 修复 | `scripts/ops/replay_project_txs.py` | 是，除非指定隔离库 | 对缺口 tx 重新按 receipt 解析并入库 |
| 安全生产同步 | `scripts/ops/deploy_production_safe.sh` | 同步白名单文件 | 文档、前端 dist、代码的受控部署 |

## 3. 推荐测试顺序

### Step 0：确认 Chainstack 环境变量

服务器执行：

```bash
cd /opt/virtuals-whale-radar
set -a
. /etc/virtuals-whale-radar/rpc.env
set +a
test -n "$CHAINSTACK_BASE_HTTP_RPC_URL"
test -n "$CHAINSTACK_BASE_WS_RPC_URL"
```

通过标准：

- 两个变量都存在。
- 不在输出中打印完整 endpoint。

### Step 1：Chainstack RPC smoke

服务器执行：

```bash
cd /opt/virtuals-whale-radar
set -a
. /etc/virtuals-whale-radar/rpc.env
set +a
./.venv/bin/python - <<'PY'
import aiohttp, asyncio, json, os, time
from virtuals_bot import RPCClient

VIRTUAL = "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

async def timed(label, fn):
    start = time.perf_counter()
    result = await fn()
    print(json.dumps({"check": label, "ok": True, "latencyMs": int((time.perf_counter() - start) * 1000), "result": result}, ensure_ascii=False))

async def main():
    http = os.environ["CHAINSTACK_BASE_HTTP_RPC_URL"]
    wss = os.environ["CHAINSTACK_BASE_WS_RPC_URL"]
    async with RPCClient(http, timeout_sec=12, max_retries=2) as rpc:
        latest = await rpc.get_latest_block_number()
        await timed("eth_blockNumber", lambda: rpc.get_latest_block_number())
        await timed("eth_getBlockByNumber_latest", lambda: rpc.get_block_by_number(latest))
        await timed("eth_getBlockByNumber_historical", lambda: rpc.get_block_by_number(max(0, latest - 50000)))
        logs = await rpc.get_logs(
            from_block=max(0, latest - 50),
            to_block=latest,
            address=VIRTUAL,
            topics=[TRANSFER],
        )
        print(json.dumps({"check": "eth_getLogs_50_blocks", "ok": True, "count": len(logs)}, ensure_ascii=False))
        if logs:
            tx = logs[-1]["transactionHash"]
            await timed("eth_getTransactionReceipt_recent", lambda: rpc.get_receipt(tx))
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
        async with session.ws_connect(wss) as ws:
            await ws.send_json({"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []})
            msg = await ws.receive()
            body = json.loads(msg.data)
            print(json.dumps({"check": "wss_eth_blockNumber", "ok": "result" in body}, ensure_ascii=False))

asyncio.run(main())
PY
```

通过标准：

- HTTP `eth_blockNumber` 成功。
- historical block 成功。
- `eth_getLogs_50_blocks` 成功，不要求 count 固定。
- recent receipt 成功。
- WSS `eth_blockNumber` 成功。

失败处理：

- HTTP 失败：不要进入 replay，先检查 Chainstack endpoint 或套餐状态。
- WSS 失败但 HTTP 成功：可以做历史 replay，但真实 live 仍有风险，需要观察 realtime 服务是否能自动重连。

### Step 2：当前生产健康检查

服务器执行：

```bash
systemctl is-active vwr-signalhub.service vwr@writer.service vwr@realtime.service vwr@backfill.service
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8080/health
```

通过标准：

- 四个服务均为 `active`。
- SignalHub 返回 `{"status":"ok"}`。
- 主程序 `/health` 返回：
  - `ok=true`
  - `runtimePaused=false`
  - `stats.ws_connected=true`

### Step 3：10 分钟 Chainstack 原生 replay

用途：快速验证一个真实项目窗口的核心链路，不写生产 DB。

ISC 示例：

```bash
cd /opt/virtuals-whale-radar
set -a
. /etc/virtuals-whale-radar/rpc.env
set +a
./.venv/bin/python scripts/ops/native_launch_replay.py \
  --virtuals-id 72752 \
  --replay-name ISC_CHAINSTACK_REPLAY \
  --duration-minutes 10 \
  --speed 5 \
  --sample-interval-sec 1 \
  --tick-sec 0.2 \
  --logs-rpc-url "$CHAINSTACK_BASE_HTTP_RPC_URL" \
  --receipt-rpc-url "$CHAINSTACK_BASE_HTTP_RPC_URL" \
  --output-dir data/replay-chainstack \
  --progress-every 50
```

通过标准：

- `replay_done` 出现。
- `txCount > 0`。
- `parsedEventCount == insertedEventCount`。
- `historicalEthCallSupported=true`。
- `logErrors=[]`。
- `finalSample.marketPriceSource=historical_pool_reserves`。
- `finalSample.estimatedFdvWanUsdWithTax` 非空。
- `finalSample.costPosition` 在有成本行后非空。

### Step 4：完整窗口 Chainstack 原生 replay

用途：压测 Chainstack 在更接近真实完整发射窗口下的稳定性。

```bash
cd /opt/virtuals-whale-radar
set -a
. /etc/virtuals-whale-radar/rpc.env
set +a
./.venv/bin/python scripts/ops/native_launch_replay.py \
  --virtuals-id <VIRTUALS_ID> \
  --replay-name <SYMBOL>_CHAINSTACK_FULL \
  --duration-minutes <WINDOW_MINUTES> \
  --speed 20 \
  --sample-interval-sec 2 \
  --tick-sec 0.2 \
  --logs-rpc-url "$CHAINSTACK_BASE_HTTP_RPC_URL" \
  --receipt-rpc-url "$CHAINSTACK_BASE_HTTP_RPC_URL" \
  --output-dir data/replay-chainstack-full \
  --progress-every 100
```

建议覆盖样本：

| 项目 | Virtuals ID | 用途 |
| --- | ---: | --- |
| ISC | `72752` | Robotic Launch / `antiSniperTaxType=2` |
| TDS | `72562` | Unicorn Launch / `60s` 快速税率衰减 |
| SR | 按项目记录填写 | 早期读取失败回归样本 |

通过标准：

- 和 Step 3 相同。
- `logSplits` 可以存在，但 `logErrors` 必须为空或可解释。
- 如果完整窗口触发 Chainstack plan/range 限制，应记录错误文本，并把该窗口标记为 `Chainstack 不适合单独承担完整窗口`。

### Step 5：前端可视化 replay

用途：验证用户实际能看到的刷新与指标，不写生产 DB。

```bash
cd /opt/virtuals-whale-radar
set -a
. /etc/virtuals-whale-radar/rpc.env
set +a
./.venv/bin/python scripts/ops/native_launch_replay.py \
  --virtuals-id 72752 \
  --replay-name ISC_CHAINSTACK_UI \
  --duration-minutes 10 \
  --speed 5 \
  --serve \
  --manual \
  --hold-open-sec 600 \
  --api-port 18080 \
  --logs-rpc-url "$CHAINSTACK_BASE_HTTP_RPC_URL" \
  --receipt-rpc-url "$CHAINSTACK_BASE_HTTP_RPC_URL" \
  --output-dir data/replay-chainstack-ui
```

打开脚本输出的 `apiProjectUrl`。观察：

- 页面能加载项目详情。
- `含税估算 FDV（万 USD）` 随 replay 推进变化。
- `Tax Rate` 展示合理。
- `打新成本位` 有事件后变化。
- tooltip 不越界。
- 控制按钮能开始、暂停、倍速、重置。

通过标准：

- 页面无明显白屏。
- 核心指标与 replay `lastSample` 一致。
- 重置后不会污染生产 DB。

### Step 6：真实项目结束后的完整性审计

用途：真实发射结束后，确认生产库没有漏 tx。

```bash
cd /opt/virtuals-whale-radar
set -a
. /etc/virtuals-whale-radar/rpc.env
set +a
./.venv/bin/python scripts/ops/audit_project_window.py \
  --config config.json \
  --project <SYMBOL> \
  --logs-rpc-url "$CHAINSTACK_BASE_HTTP_RPC_URL" \
  --block-rpc-url "$CHAINSTACK_BASE_HTTP_RPC_URL" \
  --write-repair-tx-file \
  --output data/audits/<SYMBOL>-chainstack-audit.json
```

通过标准：

- `status=green`。
- `repairCandidateTxCount=0`。
- `unresolvedDeadLetterCandidateTxCount=0`。

如果 `status=red`：

- 先读 `blockers`。
- 如果只是缺口 tx，进入 Step 7。
- 如果 `logErrors` 是 Chainstack plan/range 限制，先缩小 chunk 或记录为 Chainstack 当前套餐风险。

### Step 7：缺口 tx 修复

这是唯一可能写生产库的测试/修复步骤。执行前必须先备份生产 DB。

```bash
systemctl stop vwr@writer.service vwr@realtime.service vwr@backfill.service
cp -a /opt/virtuals-whale-radar/data/virtuals_v11.db \
  /opt/virtuals-whale-radar/data/virtuals_v11.db.bak-before-replay-$(date +%Y%m%dT%H%M%S%z)

cd /opt/virtuals-whale-radar
set -a
. /etc/virtuals-whale-radar/rpc.env
set +a
./.venv/bin/python scripts/ops/replay_project_txs.py \
  --config config.json \
  --project <SYMBOL> \
  --tx-file <REPAIR_TX_FILE> \
  --logs-rpc-url "$CHAINSTACK_BASE_HTTP_RPC_URL" \
  --block-rpc-url "$CHAINSTACK_BASE_HTTP_RPC_URL" \
  --receipt-rpc-url "$CHAINSTACK_BASE_HTTP_RPC_URL" \
  --receipt-concurrency 8 \
  --mark-scanned \
  --output data/audits/<SYMBOL>-chainstack-repair.json

systemctl start vwr@writer.service vwr@realtime.service vwr@backfill.service
```

修复后重新执行 Step 6，直到 `status=green`。

### Step 8：前端构建与部署前检查

本地执行：

```bash
cd /Users/myandong/Projects/virtuals-whale-radar/frontend/admin
npm run build
npm run lint
```

仓库根目录执行：

```bash
cd /Users/myandong/Projects/virtuals-whale-radar
bash -n scripts/ops/deploy_production_safe.sh
git diff --check
```

通过标准：

- build 成功。
- lint 成功或仅存在已知旧问题并明确记录。
- `git diff --check` 无输出。

### Step 9：安全同步检查

```bash
cd /Users/myandong/Projects/virtuals-whale-radar
scripts/ops/deploy_production_safe.sh --dry-run
```

通过标准：

- dry-run 只包含白名单代码、前端 dist、文档、ops 脚本。
- 不应出现：
  - `data/`
  - `config.json`
  - `secrets/`
  - `.venv/`
  - `node_modules/`
  - `SignalHub-main/.env`
  - `SignalHub-main/signalhub.db`

确认后再：

```bash
scripts/ops/deploy_production_safe.sh --apply
```

## 4. 测试结果记录模板

每次测试记录建议写入 `docs/<SYMBOL>-chainstack-test-YYYY-MM-DD.md`：

```markdown
# <SYMBOL> Chainstack Test - YYYY-MM-DD

## Scope

- Project:
- Virtuals ID:
- Launch mode:
- Tax config:
- Test window:
- RPC:
- Production DB touched: no / yes

## Commands

记录命令，但不要记录 endpoint token。

## Results

- txCount:
- parsedEventCount:
- insertedEventCount:
- samples:
- historicalEthCallSupported:
- logSplits:
- logErrors:
- final tokenPriceV:
- final tax-adjusted FDV(V):
- final costPosition:
- final vCostPosition:

## Verdict

- passed / failed / partial

## Follow-up

- next action:
```

## 5. 当前整合结论

当前项目测试可以整合，不需要先引入新的测试框架。整合方式如下：

1. `native_launch_replay.py` 作为主测试入口，覆盖模拟真实发射。
2. `audit_project_window.py` 作为项目结束后的完整性审计入口。
3. `replay_project_txs.py` 只作为审计失败后的修复入口。
4. `npm run build / lint` 覆盖前端构建质量。
5. `deploy_production_safe.sh --dry-run` 覆盖生产同步边界。
6. 生产 `/healthz` / `/health` / `systemctl` 覆盖运行态。

下一步最值得补的不是重写测试框架，而是一个小的 orchestrator 脚本，把 Step 1、Step 2、Step 3、Step 6 的命令串起来并输出统一 JSON 报告。当前先用本文档手动依次执行，避免在测试流程尚未稳定前引入新的维护面。
