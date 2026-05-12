# Phase 053 Virtuals Order Binding / amountOutMin

## 结论

- 已实现 `VirtualsOrderBinder`：把 direct buy 订单绑定到具体 `token / pool / slippage / deadline`。
- 已禁止执行模拟长期使用 `amountOutMin=0`：`TxSimulator` 现在把 `amountOutMin > 0` 作为绿灯条件之一。
- 默认 launch 保护参数：
  - `slippage_bps = 5000`，即 `amountOutMin = 当前池 reserve quote * 50%`。
  - `deadline_offset_sec = 180`。
  - `lp_fee_bps = 30`。
- 该阶段仍然只读，不签名、不广播，`tradeSent=false`。

## 为什么默认 50%

历史 SR/ISC direct buy 样本中，可对比 `amountOutMin / 实际到账 token` 的样本数为 `16`：

| 指标 | 数值 |
|---|---:|
| min | `31.6667%` |
| max | `86.6790%` |
| avg | `54.8272%` |

因此第一版不能用过紧的 `1% / 3%` 常规滑点，否则真实发射高波动阶段容易因为 `amountOutMin` 失败错过买点；也不能继续使用 `0`，否则没有最小成交保护。

当前折中方案是：先用当前池 reserve quote，默认只保护 quote 的 `50%`。这不是收益保护，只是防止极端错误成交；真正是否允许签名仍由 `eth_call / estimateGas / balance / allowance / deadline / amountOutMin` 共同决定。

## 池子兼容性

执行层支持两种池子布局：

- 标准池：可读取 `token0 / token1 / getReserves / decimals`。
- Virtuals internal pool fallback：`token0 / token1` 可能 revert，但 `getReserves / decimals` 可读；此时按主程序已有 reserve 布局启发式推断 token reserve 与 VIRTUAL reserve。

这个 fallback 是必要的：TDS internal pool 对 `token0/token1` 会 revert，但主程序价格计算已经依赖 fallback，执行层不能只支持标准 Uniswap 风格池。

## 真实只读 Probe

命令：

```bash
python3 scripts/ops/tx_simulator_probe.py \
  --config config.json \
  --from-address 0xfa16eb4a744d68582d4f2f7144b339f00952bd42 \
  --token-address 0x2fb742df1e8707247e75c620c694245ec5f2eced \
  --pool-address 0x7caabe5fdb0c393d205ded2d1e27b8a457fd1957 \
  --amount-v 25 \
  --slippage-bps 5000 \
  --deadline-offset-sec 180 \
  --output-json data/backtests/tx-simulator-probe-tds-bound-minout-readonly-20260510.json
```

结果：

| 检查项 | 结果 |
|---|---|
| `tradeSent` | `false` |
| `green` | `false` |
| `amountOutMinOk` | `true` |
| `deadlineOk` | `true` |
| `balanceOk` | `false` |
| `allowanceOk` | `true` |
| `ethCallOk` | `false`，原因是测试地址当前 VIRTUAL 余额不足 |
| `estimateGasOk` | `false`，原因同上 |

输出文件：

- `data/backtests/tx-simulator-probe-tds-bound-minout-readonly-20260510.json`

## 当前边界

- 支持范围仍然只包含 direct buy：router `0x1a540088125d00dd3990f9da45ca0859af4d3b01` + selector `0x706910ff`。
- team/initialization route 与 alternate/aggregator route 不纳入第一版自动买入。
- 没有 burner wallet 余额和授权绿灯前，不进入签名。
- 没有手动 canary allow gate 前，不允许广播。
