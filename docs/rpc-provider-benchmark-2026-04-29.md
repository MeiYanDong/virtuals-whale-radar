# RPC Provider Benchmark - 2026-04-29

## 0. 当前生产结论

2026-04-29 Ankr 充值复测后，当前生产推荐已经从“公共 logs + Chainstack receipt”升级为：

1. 主路径：`Ankr logs + Ankr receipt + Ankr block`
2. 默认并发：`16`
3. 手动 replay / 批处理加速档：`24`，需要继续观察 Ankr 限速
4. Base official：保留为 logs 备用
5. Alchemy 免费 key：保留为小窗口 / 低并发备用，不作为完整窗口主路径
6. Chainstack 当前 plan：不再作为 Base 历史 `eth_getLogs` / historical block 主路径

下面第 2-5 节保留为 Ankr 充值前的历史测试记录；如与第 6 节冲突，以本节和第 6 节为准。

## 1. 测试口径

测试从阿里云轻量应用服务器执行：

- 服务器：`47.243.172.165`
- 项目：`SR`
- 测试交易：已入库的 `SR` 样本 tx
- 历史块：`44629967`
- `SR 50 blocks`：`44629927 -> 44629976`
- `SR full window`：`44629927 -> 44632913`
- logs 查询使用项目真实的 `4` 组 `eth_getLogs` filter
- QuickNode：按用户要求跳过
- Alchemy key：已测试，文档中不记录完整 key

## 2. 免费 / 当前套餐测试结果

| Provider | basic avg | receipt avg | historical block | 50 blocks logs | full window logs | 判断 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Chainstack current 1 | `72ms` | `79ms` | 不可用 | 不可用 | 不可用 | receipt 快，但当前 plan 不能做历史 logs / block |
| Chainstack current 2 | `68ms` | `71ms` | 不可用 | 不可用 | 不可用 | 同上 |
| Chainstack current 3 | `80ms` | `69ms` | 不可用 | 不可用 | 不可用 | 同上 |
| dRPC public no-key | `51ms` | `360ms` | `5/6` 成功，`254ms` | `3/3` 成功，`1793ms` | `1/3` 成功，`1704ms` | 很快但完整窗口不稳 |
| Base official public | `280ms` | `345ms` | `414ms` | `3/3` 成功，`1170ms` | `3/3` 成功，`2926ms` | 当前免费 logs 兜底里最稳 |
| PublicNode | `205ms` | `227ms` | `204ms` | `0/3`，timeout | `0/3`，timeout | 不适合 logs 主路径 |
| Ankr no-key | 未授权 | 未测 | 未测 | 未测 | 未测 | 免费账号需要 API key |
| Alchemy demo no-key | `429` | 未测 | 未测 | 未测 | 未测 | 不能代表免费账号 |

Chainstack 当前 plan 的历史查询报错：

```text
Archive, Debug and Trace requests are not available on your current plan.
```

## 3. Alchemy 免费 key 追加测试

Alchemy Base mainnet 免费 key：

| 指标 | 结果 |
| --- | ---: |
| `eth_blockNumber` | `81ms` avg |
| `eth_getTransactionReceipt` | `92ms` avg |
| historical `eth_getBlockByNumber` | `82ms` avg |
| 直接查 `50 blocks logs` | 失败，免费层限制 `eth_getLogs` 最大 `10` block range |
| 直接查 full window logs | 失败，同上 |
| `10 blocks logs`，4 组 filter | `201ms` avg，`5/5` 成功 |
| `50 blocks logs` 拆成 `5 x 10 blocks` | `1063ms` avg，`3/3` 成功 |

Alchemy 免费层完整窗口限制测试：

- 按 `10` block chunk 无限制连续跑：触发 `CUPS` 限速，失败。
- 并发 `10` 跑完整窗口：触发 `CUPS` 限速，失败。
- 限速到 `10 eth_getLogs calls/sec` 后仍在第 `178` 个 chunk 附近触发 `429`。
- 已处理 `188 / 299` 个 chunk，耗时约 `79s`，未完成完整窗口。

结论：

- Alchemy 免费 key 对 receipt 和 historical block 很快。
- Alchemy 免费 key 可做小窗口 logs fallback。
- Alchemy 免费 key 不适合直接做 `SR` 完整窗口 logs 主路径，除非进一步降速、加 retry，代价是完整窗口可能变成数分钟级。
- Alchemy Sepolia endpoint 只做连通性探测，`eth_blockNumber` 可用，约 `137ms`；它不参与生产 Base mainnet 数据链路。

## 4. 历史推荐（Ankr 充值前，已被第 6 节取代）

免费 / 当前套餐下，当时的临时推荐是：

1. `eth_getLogs` 主兜底：`https://mainnet.base.org`
2. `eth_getLogs` 辅助兜底：`https://base.drpc.org`
3. 小窗口 logs / receipt / historical block fallback：Alchemy 免费 key
4. receipt 主路径：Chainstack current
5. publicnode：保留末位或移出 logs 主链路
6. llamarpc：服务器访问曾返回 `403`，不放主链路

当时的付费升级优先级是：

1. Chainstack 升级到支持 Archive 的 plan 后，先重跑同一套 `SR` benchmark。
2. 如果 Chainstack archive full window logs 稳定低于 `1-2s` 且成功率接近 `10/10`，它可以升级为 logs / block / receipt 主路径。
3. Alchemy PAYG 适合作为第二主力，因为免费 key 已证明 receipt / block 很快，付费后可解除 logs range / throughput 限制。
4. dRPC 适合作为低成本 fallback，但当前 no-key 完整窗口成功率不够稳。

## 5. 历史配置含义（Ankr 充值前，已被第 6 节取代）

短期不升级套餐时：

- logs / historical block：继续优先 `mainnet.base.org`
- receipt / token metadata：继续优先 Chainstack
- Alchemy 免费 key：只适合小窗口 fallback，不能直接替换主 logs RPC
- replay 工具必须保留 `--logs-rpc-url` / `--block-rpc-url` / `--receipt-rpc-url` 分离

升级后要重新测试：

- `eth_getLogs` 50 blocks
- `eth_getLogs` full SR window
- historical `eth_getBlockByNumber`
- `602` 笔 receipt replay

## 6. Ankr 充值后组合复测

Ankr Base endpoint 充值后，在生产轻量应用服务器上重新做 SR 真实窗口 benchmark。

### 6.1 SR 1/20 窗口多轮分段测试

范围：`44629927 -> 44630075`，共 `149` blocks，发现 `33` 个 tx，去重后 `32` 个 block。

| 功能段 | 最快稳定 Provider | 多轮结果 | 备注 |
| --- | --- | ---: | --- |
| `eth_getLogs` | Ankr | `5/5` 成功，p50 `860ms`，p90 `952ms` | Base official p50 `1056ms`，dRPC p50 `1705ms` |
| `eth_getTransactionReceipt` | Ankr | `5/5` 成功，p50 `347ms`，p90 `404ms` | Alchemy p50 `387ms`；Chainstack backfill 本轮只有 `1/5` 成功 |
| historical `eth_getBlockByNumber` | Alchemy / Ankr | Alchemy p50 `313ms`，Ankr p50 `322ms`，均 `5/5` 成功 | dRPC free 本轮 `0/5` |

自动组合排名中，SR 1/20 最优组合是：

1. `Ankr logs + Ankr receipt + Alchemy block`：p50 `1520ms`
2. `Ankr logs + Ankr receipt + Ankr block`：p50 `1529ms`
3. `Ankr logs + Alchemy receipt + Alchemy block`：p50 `1560ms`

### 6.2 完整 SR logs 窗口稳定性

范围：`44629927 -> 44632913`，共 `2987` blocks。

| Provider | 结果 |
| --- | ---: |
| Ankr | `5/5` 成功，p50 `1682ms`，p90 `2253ms`，发现 `754` candidate tx |
| Base official | `5/5` 成功，p50 `3164ms`，p90 `4615ms`，发现 `754` candidate tx |
| dRPC free | `1/2` 成功 |
| publicnode | `0/2` 成功 |

### 6.3 完整 SR 全链路组合测试

完整链路定义：完整 SR logs 窗口 + `754` 个 candidate receipt + `600` 个 candidate block timestamp。该测试是偏保守的上限，因为正式 replay 只会对相关交易继续取 timestamp。

| 组合 | 结果 |
| --- | ---: |
| Ankr 全包 | `3/3` 成功，平均 `10.9s`，中位 `10.4s` |
| Ankr logs + Ankr receipt + Alchemy block | `0/3` 成功，Alchemy block 阶段触发 `429 / CUPS` |
| Ankr logs + Alchemy receipt + Alchemy block | `0/3` 成功，Alchemy receipt 阶段触发吞吐限制 |
| Base official logs + Ankr receipt + Alchemy block | `0/3` 成功，Alchemy block 阶段触发吞吐限制 |

结论：Alchemy 在小窗口很快，但当前免费 key 不适合完整 SR 规模的并发 receipt/block 主路径。Ankr 充值后可以单独承担完整 SR 历史发现、receipt、block timestamp。

### 6.4 Ankr 并发参数

完整 SR 全链路使用 Ankr 全包测试不同并发：

| 并发 | 成功率 | 平均耗时 |
| ---: | ---: | ---: |
| `4` | `2/2` | `25.8s` |
| `8` | `2/2` | `12.5s` |
| `12` | `2/2` | `8.5s` |
| `16` | `2/2` | `6.3s` |
| `24` | `1/1` | `5.0s` |

生产默认建议：

- 默认并发先设 `16`，速度和稳定性平衡最好。
- `24` 可以作为手动 replay / 批处理加速档，但需要更长时间观察是否触发 Ankr 限速。
- 当前最优主路径：`Ankr logs + Ankr receipt + Ankr block`。
- Base official 保留 logs 备用；Alchemy 保留小窗口/低并发备用；Chainstack 当前 plan 不再作为历史 logs/block 路径。
