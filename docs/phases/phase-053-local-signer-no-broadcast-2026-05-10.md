# Phase 053 LocalSigner / No Broadcast

## 结论

- 已实现 `LocalSigner`。
- 已接入 `eth-account==0.13.7`。
- 已完成本地签名 smoke test：使用临时测试账户签 EIP-1559 raw tx，随后 `recover_transaction` 校验 sender。
- 该阶段仍然不广播，`SignedTransaction.broadcast_allowed=false`。

## 安全边界

- 私钥只允许来自环境变量：`VWR_BURNER_PRIVATE_KEY`。
- 禁止通过 CLI 参数传私钥。
- 禁止打印私钥、seed phrase、raw private key。
- `LocalSigner` 签名前强制检查：
  - `amountOutMin > 0`。
  - `nonce` 已填充。
  - `gas` 已填充。
  - `maxFeePerGas / maxPriorityFeePerGas` 已填充。
  - 私钥派生地址必须等于 unsigned tx 的 `from`。
  - 签名后 recover 出来的 sender 必须等于 unsigned tx 的 `from`。

## 已验证

测试命令：

```bash
.venv/bin/python scripts/ops/test_launch_execution_pipeline.py
```

覆盖：

- calldata parity。
- live-pool `amountOutMin` binding。
- `TxSimulator` 只读绿灯/阻断逻辑。
- `LocalSigner` 本地签名和 recover 校验。
- `SafeBroadcaster` 默认拒绝广播。

## 未完成边界

- 还没有用真实 burner 钱包私钥做 no-broadcast 演练。
- 还没有在真实 burner 钱包余额和 allowance 都满足时跑 simulation green。
- 还没有执行主网 canary。
- 广播默认仍关闭，没有手动 canary allow gate 前不能发送交易。
