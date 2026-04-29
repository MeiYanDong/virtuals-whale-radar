# Virtuals Protocol 代币买入成本计算 — 完整指南

## 一、我们要算什么？

当你在 Virtuals Protocol 上买入一个 AI Agent 的代币（比如 FAT），你需要知道：

- 我花了多少钱？（买入金额）
- 我买到了多少代币？（买入数量）
- 每个代币多少钱？（单位成本）

问题是：这些代币没有上交易所，没有 CoinGecko 价格，甚至没有公开的流动性池。
所以我们需要从链上交易数据里，一步步把成本算出来。

---

## 二、先搞懂整个交易是怎么发生的

### 2.1 你做了什么

你在 Virtuals 平台上点了"买入 FAT 代币"，花了 150 个 VIRTUAL 代币。

### 2.2 链上实际发生了什么

你的 150 VIRTUAL 并不是直接换成了 FAT。它经过了一条流水线：

```
你的钱包 (150 VIRTUAL)
    │
    ▼
收银台 — BondingV5 合约
    │
    ├── 扣税 1% ──→ 1.5 VIRTUAL → AgentTaxV2（税收合约）→ 创建者/协议金库
    │
    └── 剩余 99% ─→ 148.5 VIRTUAL → FRouterV3（路由器）
                                        │
                                        ▼
                                   Pair 池子合约
                                   （里面装着 FAT 和 VIRTUAL）
                                        │
                                        ▼
                                   吐出 1,698,115.06 FAT → 你的钱包
```

### 2.3 涉及的合约（全部在 Base 链上）

| 合约角色 | 代理地址 (Proxy) | 实现地址 (Implementation) | 干什么的 |
|---------|-----------------|-------------------------|---------|
| 收银台 BondingV5 | `0x1A540088125d00dD3990f9dA45CA0859af4d3B01` | `0xa9668b3205f67b497de1f6350cb29ae0ca3899e8` | 所有买卖的入口，验证交易、分发资金 |
| 路由器 FRouterV3 | `0x02FE8eC3d9BBf7318eb54590bcC39198a8b47deD` | `0x42Ea980E773ff5b18cc1c56f2f6db8bf47d55e32` | 计算价格、执行兑换 |
| 税收 AgentTaxV2 | `0x617Fd668c5b0d1906C0B3E7E3E49d1409Df0a528` | `0x8fbc314aaa3543b864fd38f62b3d52b9032e55f5` | 收税、分配给创建者和协议 |
| 配置 BondingConfig | `0x488db0978b34c6fd901760b9024b565c1117c7c8` | `0xc81844668fc9ec385b477848171a014a5aba1b6a` | 存储税率、反狙击等参数 |
| 协议 Owner | `0xc31cf1168b2f6745650d7b088774041a10d76d55` | — | 协议管理员 |

| 代币/池子 | 地址 |
|----------|------|
| VIRTUAL 代币 | `0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b` |
| FAT 代币 | `0x3781934f9cc3b5157eab5f663b144103409cfffb` |
| FAT/VIRTUAL 交易池 | `0xd331e7Bdce240342E452ab8C808E26f24DbBcffB` |

---

## 三、从一笔交易里提取成本数据

### 3.1 找到交易

示例交易：
```
https://basescan.org/tx/0x05ad32078f9c71c7e4d09762c69d8e5669542e365f2daf0ed7d3870637ff16b9
```

### 3.2 看 Token Transfers（代币转账记录）

在 BaseScan 的交易页面上，找到 "ERC-20 Tokens Transferred" 部分，会看到 4 笔转账：

```
转账 ①  你 → Pair池    148.5 VIRTUAL    ← 实际进池兑换的部分（99%）
转账 ②  你 → Router    1.5 VIRTUAL      ← 税（1%）
转账 ③  Router → Tax   1.5 VIRTUAL      ← 税从路由器转到税收合约
转账 ④  Pair池 → 你    1,698,115.06 FAT ← 你买到的代币
```

### 3.3 从转账记录里提取关键数据

我们需要 3 个数字：

| 数据 | 怎么找 | 本例的值 |
|------|--------|---------|
| 税额 | 转账 ② 的金额 | 1.5 VIRTUAL |
| 实际进池金额 | 转账 ① 的金额 | 148.5 VIRTUAL |
| 买到的代币数量 | 转账 ④ 的金额 | 1,698,115.06 FAT |

### 3.4 反推总付出金额

```
已知：税率 = 1%
已知：税额 = 1.5 VIRTUAL

总付出 = 税额 ÷ 税率 = 1.5 ÷ 0.01 = 150 VIRTUAL ✓

验证：实际进池 = 总付出 × 99% = 150 × 0.99 = 148.5 VIRTUAL ✓
```

> 为什么要从税额反推？
> 因为有些交易的 Transfer 事件可能合并或拆分，但税那一笔是独立的、确定的。
> 知道税额和税率，就能 100% 确定总付出量。

---

## 四、把 VIRTUAL 数量换算成美元

### 4.1 问题

你付出了 150 VIRTUAL，但"150 VIRTUAL"不直观，你需要知道这是多少美元。

### 4.2 获取 VIRTUAL 的美元价格

VIRTUAL 是一个有公开流动性池的代币，价格很容易获取：

**方法 A：第三方 API（简单）**
- CoinGecko: `https://api.coingecko.com/api/v3/simple/token_price/base?contract_addresses=0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b&vs_currencies=usd`
- CoinMarketCap
- GeckoTerminal

**方法 B：链上读取（去中心化，不依赖第三方）**
- 读 VIRTUAL/WETH 池子的 reserves，算出 VIRTUAL 的 ETH 价格
- 再用 ETH/USD 价格换算

### 4.3 计算美元金额

```
VIRTUAL 价格 = $0.76（交易发生时的价格）
买入金额 = 150 × $0.76 = $114.00
```

---

## 五、计算 FAT 代币的单位成本

```
单位成本 = 买入金额 ÷ 买到的数量
         = $114.00 ÷ 1,698,115.06
         = $0.0000671 / FAT
```

或者用 VIRTUAL 计价：
```
单位成本 = 150 VIRTUAL ÷ 1,698,115.06 FAT
         = 0.0000883 VIRTUAL / FAT
```

---

## 六、获取 FAT 的当前价格（用来算盈亏）

FAT 没有上交易所，没有 CoinGecko 收录。它的价格只存在于 bonding curve 池子里。

### 6.1 什么是 bonding curve 池子

想象一个箱子，里面装着两堆东西：
- 一堆 FAT 代币（目前 2.37 亿个）
- 一堆 VIRTUAL 代币（目前 26,544 个）

价格 = 这两堆东西的比例。

有人买 FAT → FAT 变少，VIRTUAL 变多 → FAT 涨价
有人卖 FAT → FAT 变多，VIRTUAL 变少 → FAT 跌价

### 6.2 方法一：读池子 reserves（轻量）

直接调用 Pair 池合约的 `getReserves()` 函数：

```bash
curl -s -X POST https://mainnet.base.org \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "eth_call",
    "params": [{
      "to": "0xd331e7Bdce240342E452ab8C808E26f24DbBcffB",
      "data": "0x0902f1ac"
    }, "latest"],
    "id": 1
  }'
```

返回值是两个 256 位整数（hex 编码），解码后：
```
reserve0 = FAT 数量   = 237,337,530.15 FAT
reserve1 = VIRTUAL 数量 = 26,544.47 VIRTUAL
```

计算价格：
```
1 FAT = reserve1 ÷ reserve0
      = 26,544.47 ÷ 237,337,530.15
      = 0.0001118 VIRTUAL
      = $0.0000847（按 VIRTUAL=$0.7578）
```

> 注意：这是"理论价格"，不含交易手续费。实际买卖时会有滑点。

### 6.3 方法二：调用 Router 的 getAmountsOut（精确）

调用 FRouterV3 的 `getAmountsOut(token, assetToken, amountIn)` 函数：

```bash
# 问：1 VIRTUAL 能换多少 FAT？
curl -s -X POST https://mainnet.base.org \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "eth_call",
    "params": [{
      "to": "0x02FE8eC3d9BBf7318eb54590bcC39198a8b47deD",
      "data": "0x45608d000000000000000000000000003781934f9cc3b5157eab5f663b144103409cfffb0000000000000000000000000b3e328455c4059eeb9e3f84b5543f74e24e7e1b0000000000000000000000000000000000000000000000000de0b6b3a7640000"
    }, "latest"],
    "id": 1
  }'
```

其中 `data` 的构成：
```
0x45608d00                                                         ← 函数选择器 getAmountsOut(address,address,uint256)
0000000000000000000000003781934f9cc3b5157eab5f663b144103409cfffb   ← FAT 代币地址（token）
0000000000000000000000000b3e328455c4059eeb9e3f84b5543f74e24e7e1b   ← VIRTUAL 代币地址（assetToken）
0000000000000000000000000000000000000000000000000de0b6b3a7640000   ← 1e18（1 个 VIRTUAL，18 位小数）
```

返回值解码后：
```
8,842.91 FAT（即 1 VIRTUAL 能换到 8,842.91 FAT）

反过来：1 FAT = 1/8842.91 = 0.0001131 VIRTUAL = $0.0000857
```

### 6.4 两种方法对比

| | 读 reserves | 调 getAmountsOut |
|---|---|---|
| 精确度 | 理论价格，不含手续费 | 实际可成交价格，含手续费 |
| 调用次数 | 1 次 | 1 次 |
| Gas | 0（view 调用） | 0（view 调用） |
| 适用场景 | 快速估算、监控价格趋势 | 精确计算成本、模拟交易 |
| 推荐 | 看大盘用 | 算成本用 ✓ |

---

## 七、完整计算公式汇总

```
输入：
  tx_hash        = 一笔买入交易的哈希
  tax_rate       = 0.01（1%）
  virtual_price  = VIRTUAL 的美元价格（从 CoinGecko 等获取）

从链上读取：
  tax_amount     = 转给税收合约的 VIRTUAL 数量（从 Transfer 事件中提取）
  fat_received   = 转给买家的 FAT 数量（从 Transfer 事件中提取）

计算：
  total_virtual_paid = tax_amount ÷ tax_rate
  cost_usd           = total_virtual_paid × virtual_price
  unit_cost_usd      = cost_usd ÷ fat_received
  unit_cost_virtual  = total_virtual_paid ÷ fat_received

输出：
  总付出：150 VIRTUAL = $114.00
  买到：  1,698,115.06 FAT
  单价：  $0.0000671 / FAT
```

---

## 八、如何获取历史交易的 VIRTUAL 价格

当前价格好查，但如果要算历史交易的成本，需要交易发生那一刻的 VIRTUAL 价格。

### 方法 A：用交易的区块号查历史价格
```
1. 从交易中拿到 blockNumber
2. 调用 VIRTUAL/WETH 池子的 getReserves()，传入该 blockNumber
3. 算出那个区块时的 VIRTUAL 价格
```

### 方法 B：用第三方历史价格 API
```
CoinGecko: /coins/virtual-protocol/market_chart/range?vs_currency=usd&from=TIMESTAMP&to=TIMESTAMP
```

### 方法 C：BaseScan 上直接看
BaseScan 在 Token Transfer 旁边会标注美元估值（如 "$112.95"），这个值就是用交易时的价格算的。

---

## 九、这些地址是怎么找到的

### 第一步：从交易的 Transfer 事件横向展开

一笔交易的 Token Transfer 记录会暴露所有参与的地址：
```
交易 → 看到调用了 0x1A54...（BondingV5）
     → 看到 VIRTUAL 转给了 0xd331...（Pair 池）
     → 看到 VIRTUAL 转给了 0x02FE...（Router）
     → 看到 FAT 从 0xd331... 转出（确认它是池子）
     → 看到 VIRTUAL 从 0x02FE... 转给 0x617F...（税收流向）
```

### 第二步：用 RPC 调用纵向深挖

```
BondingV5.router()   → 返回 0x02FE...（确认是 FRouterV3）
BondingV5.owner()    → 返回 0xc31c...（协议 Owner）
FRouterV3.factory()  → 返回 0x488d...（BondingConfig）
```

### 第三步：读 ERC-1967 存储槽找实现合约

每个代理合约（Proxy）的实现地址存在固定位置：
```
存储槽 = 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc

eth_getStorageAt(proxy_address, 上面这个槽) → 返回 implementation 地址
```

全部是链上公开数据，任何人都可以查。

---

## 十、关键概念解释

### Bonding Curve（联合曲线）
一种自动定价机制。不需要人来挂单，价格由池子里两种代币的比例自动决定。买的人越多，价格越高。核心公式：`x × y = k`（恒定乘积）。

### Proxy 合约（代理合约）
智能合约一旦部署就不能修改。Proxy 模式是一种升级方案：用户调用 Proxy 地址，Proxy 把调用转发给 Implementation（实现合约）。升级时只需要换 Implementation 地址，用户感知不到变化。

### 毕业（Graduation）
当一个 agent 代币的 bonding curve 池子累积到 42,000 VIRTUAL 时，代币"毕业"——自动迁移到 Uniswap 正式池子，变成一个正常的可交易代币。FAT 目前池子里只有 ~26,544 VIRTUAL，还没毕业。

### 税率（Tax）
每笔买入扣 1% 给协议/创建者。这是写在合约里的，不可逃避。卖出也可能有税，具体看 BondingConfig 的配置。

### View 调用
读取链上数据但不改变任何状态的调用。不需要发交易，不消耗 Gas，免费且即时返回结果。`getReserves()` 和 `getAmountsOut()` 都是 view 调用。
