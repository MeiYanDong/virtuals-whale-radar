# Phase 053 - Virtuals Buy Spender Trace

## 结论

- 直接买入入口 router 仍然是 `0x1a540088125d00dd3990f9da45ca0859af4d3b01`。
- 但 VIRTUAL `transferFrom` 的实际 spender 是 `0x02fe8ec3d9bbf7318eb54590bcc39198a8b47ded`。
- 因此 TxSimulator 的 allowance 检查必须查 `allowance(owner, spender)`，不能查 `allowance(owner, router)`。
- SR/ISC 历史样本在交易前一个 block：owner balance 足够、router allowance 不足、actual spender allowance 足够。
- 本阶段仍然不签名、不广播。

## 样本

| Project | Tx | Owner Balance OK | Router Allowance OK | Actual Spender OK | Actual Spender |
| --- | --- | --- | --- | --- | --- |
| SR_EVENT_REPLAY | `0x598d50a8...cdab760e` | yes | no | yes | `0x02fe8ec3d9bbf7318eb54590bcc39198a8b47ded` |
| ISC_EVENT_REPLAY | `0x38d9b3f3...5e982840` | yes | no | yes | `0x02fe8ec3d9bbf7318eb54590bcc39198a8b47ded` |
