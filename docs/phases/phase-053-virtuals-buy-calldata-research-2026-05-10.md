# Phase 053 - Virtuals Buy Calldata Research

## 结论

- 历史成功买入交易使用固定路由 `0x1a540088125d00dd3990f9da45ca0859af4d3b01`。
- selector 为 `0x706910ff`，BaseScan 将其解码为 `buy(uint256 amountIn_, address tokenAddress_, uint256 amountOutMin_, uint256 deadline_)`。
- `value` 为 `0`，VIRTUAL 通过 ERC-20 transfer/allowance 进入路由，不是原生 ETH value。
- 标准 calldata 长度为 132 bytes；部分交易会在 4 个 ABI 参数后追加 29 bytes 尾部标签，链上执行成功，合约实际使用前 4 个参数。
- OrderBuilder 当前只允许生成标准 4 参数 canonical calldata；尾部标签不参与构造。
- 本阶段仍然不签名、不广播。
- BaseScan 参考样本：https://basescan.org/tx/0x7bdf8e9d0e3359eb20b79b92ce8b9659357dfef3dda5f8eaf74cb77370fd357f

## 样本摘要

- generatedAt: `2026-05-10T10:53:38Z`
- rpc: `https://base-mainnet.core.chainstack.com/***`
- samples: `19`
- directBuySamples: `18`
- alternateRouteSamples: `1`
- selectorCounts: `{"0x706910ff": 18, "0x1fad948c": 1}`
- routerCounts: `{"0x1a540088125d00dd3990f9da45ca0859af4d3b01": 18, "0x5ff137d4b0fdcd49dca30c7cf57e578a026d2789": 1}`
- tailByteCounts: `{"29": 16, "0": 2, "unsupported": 1}`

## Direct Buy 样本表

| Project | Tx | Amount V | Token | Min Out | Deadline | Canonical | Tail | Status |
| --- | --- | ---: | --- | ---: | ---: | --- | ---: | --- |
| SR_EVENT_REPLAY | `0x598d50a8...cdab760e` | 100 | `0x10c56f00...f0031ac9` | 0 | 1776222098 | yes | 0 | 0x1 |
| SR_EVENT_REPLAY | `0x9ddfd319...d72079a4` | 647.177222 | `0x10c56f00...f0031ac9` | 38239742051299996000000 | 1776049641 | prefix | 29 | 0x1 |
| SR_EVENT_REPLAY | `0x4bf27151...c1722338` | 6.677043 | `0x10c56f00...f0031ac9` | 394184923099999930000 | 1776049654 | prefix | 29 | 0x1 |
| SR_EVENT_REPLAY | `0x22f83e1c...874b6154` | 50 | `0x10c56f00...f0031ac9` | 2951735369850000000000 | 1776049663 | prefix | 29 | 0x1 |
| SR_EVENT_REPLAY | `0x39767fea...41019d61` | 1 | `0x10c56f00...f0031ac9` | 59035991550000000000 | 1776049670 | prefix | 29 | 0x1 |
| SR_EVENT_REPLAY | `0x39e33cdd...0b731b9a` | 100 | `0x10c56f00...f0031ac9` | 5467806136320000000000 | 1776049680 | prefix | 29 | 0x1 |
| SR_EVENT_REPLAY | `0xd0eae261...bc3df84e` | 100 | `0x10c56f00...f0031ac9` | 5900114069550000000000 | 1776049696 | prefix | 29 | 0x1 |
| SR_EVENT_REPLAY | `0xf909e9a1...99e2ea07` | 22356.8032035 | `0x10c56f00...f0031ac9` | 4852156095108080000000000 | 1776049902 | prefix | 29 | 0x1 |
| SR_EVENT_REPLAY | `0x929a0d58...31afa459` | 20000 | `0x10c56f00...f0031ac9` | 4588393185176820000000000 | 1776049885 | prefix | 29 | 0x1 |
| ISC_EVENT_REPLAY | `0x851e53bd...92a78f4d` | 0.1 | `0x2b8126fa...ca755d0d` | 7339164200000000000 | 1777473507 | prefix | 29 | 0x1 |
| ISC_EVENT_REPLAY | `0x38d9b3f3...5e982840` | 600 | `0x2b8126fa...ca755d0d` | 87091147945659990000000 | 1777473541 | prefix | 29 | 0x1 |
| ISC_EVENT_REPLAY | `0xa2e7e2b7...0a44754b` | 140.58647267 | `0x2b8126fa...ca755d0d` | 20632867793800000000000 | 1777473540 | prefix | 29 | 0x1 |
| ISC_EVENT_REPLAY | `0x7dc97cc0...abeed0aa` | 0.1 | `0x2b8126fa...ca755d0d` | 0 | 1777646068 | yes | 0 | 0x1 |
| ISC_EVENT_REPLAY | `0xc500c687...80af4cb7` | 1000 | `0x2b8126fa...ca755d0d` | 203053069986800000000000 | 1777473599 | prefix | 29 | 0x1 |
| ISC_EVENT_REPLAY | `0x18989b5f...211c4091` | 100 | `0x2b8126fa...ca755d0d` | 21949764901699997000000 | 1777473602 | prefix | 29 | 0x1 |
| ISC_EVENT_REPLAY | `0x9dd78bd7...c269e161` | 4000 | `0x2b8126fa...ca755d0d` | 863751928544040000000000 | 1777473606 | prefix | 29 | 0x1 |
| ISC_EVENT_REPLAY | `0x64998ae0...975370c2` | 100 | `0x2b8126fa...ca755d0d` | 28507671208859996000000 | 1777473612 | prefix | 29 | 0x1 |
| ISC_EVENT_REPLAY | `0xea2b4e83...2d92921c` | 4135.34092066 | `0x2b8126fa...ca755d0d` | 2168056528496100000000000 | 1777474623 | prefix | 29 | 0x1 |

## Alternate Route 样本

这些交易也触发了目标池买入事件，但交易入口不是 Virtuals 直接 buy 路由。它们更像聚合器/钱包路由成交，不作为第一版 OrderBuilder 的构造目标。

| Project | Tx | Router | Selector | Input Bytes | Amount V | Status |
| --- | --- | --- | --- | ---: | ---: | --- |
| SR_EVENT_REPLAY | `0x6ee6f62d...72434d53` | `0x5ff137d4...026d2789` | `0x1fad948c` | 26564 | 150 | 0x1 |

## OrderBuilder 边界

- 已完成：低层 calldata encoder 可以重建标准 4 参数买入 calldata，并对历史 canonical 样本 exact parity。
- 已完成：带尾部标签的历史交易可以做到 canonical prefix parity，尾部不进入 OrderBuilder。
- 未完成：把 `BuyIntent` 绑定到具体 token、slippage、deadline、allowance、nonce、gas。
- 未完成：`eth_call` / allowance / balance / gas estimate / receipt verifier。
- 未完成：burner wallet 签名和手动 canary 广播。
