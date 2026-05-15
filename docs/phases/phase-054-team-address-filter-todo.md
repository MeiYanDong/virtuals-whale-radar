# Phase 054 Team Address Filter Todo

## 1. 后端

- [x] 新增 `team_address_overrides` 表。
- [x] 新增管理员覆盖规则查询、写入和删除方法。
- [x] 新增手动排除 / 手动纳入管理员 API。
- [x] 在 overview 榜单聚合中返回团队过滤状态和覆盖来源。
- [x] 固定覆盖优先级：手动排除 > 手动纳入 > 自动识别。
- [x] 修正手动覆盖不依赖首笔买入特征，避免特征缺失导致管理员规则失效。
- [x] 新增首分钟零税且当时预期应有税的硬过滤规则，不再要求买入份额阈值。

## 2. 前端

- [x] 主大户榜单过滤掉 `costExcluded=true` 地址。
- [x] 新增管理员唯一默认折叠的“自动过滤”控件。
- [x] 大户榜单表格不展示团队/疑似团队地址。
- [x] 大户榜单表格不展示“团队过滤”字段或行内过滤按钮。
- [x] 支持管理员输入钱包地址和备注，将地址加入排除。
- [x] 支持管理员从审核区点击“纳入成本位”。
- [x] 显示“疑似团队 / 手动排除 / 手动纳入”状态标签。

## 3. 验证

- [x] `python3 -m py_compile virtuals_bot.py`。
- [x] `npm run build`。
- [x] `npm run lint`。
- [x] 本地 writer 重启后 `/health` 正常。
- [x] 本地 API 测试：排除、纳入、删除覆盖规则均正常。
- [x] 本地前端 UI 测试：加入排除、审核区展示、清理后空状态均正常。
- [x] 验证 `0x81f7ca6af86d1ca6335e44a2c28bc88807491415` 会被自动过滤。
- [x] 修复手动排除后“纳入成本位”按钮因 pending wallet 残留而无法点击的问题。
- [x] 2026-05-15 确认当前生产部署已包含 `team_address_overrides`、管理员团队过滤 API 和前端钱包编辑修复相关代码；具体部署 commit 以服务器 `DEPLOYED_COMMIT` 为准。
- [x] 2026-05-15 生产健康检查通过：`writer / realtime / backfill / SignalHub / nginx` 均 active，`/health ok=true`，`/healthz status=ok`。

## 4. 待办

- [x] 同步 GitHub 前做一次完整 `git diff` 审核。
- [x] 代码已随生产安全同步进入远端。
- [x] 将 Phase 053 的团队/初始化 route 识别接入自动过滤：事件入库持久化 `tx_to / tx_selector / calldata_bytes`。
- [x] 自动过滤规则新增高置信条件：`to == direct router`、`selector == 0x214013ca`。
- [x] 回放验证 SR/ISC/TDS：团队/初始化地址应被过滤，普通 `0x706910ff` direct buy 不误杀；报告见 `docs/phases/phase-054-route-filter-validation-2026-05-15.md`。
- [x] 生产 overview API 烟测通过：管理员短期 session 只读访问项目列表与 ROO overview，返回 `ok=true`、`whaleBoard=20`、`trackedWallets=6`、`hiddenTeamRows=1`。
- [x] 生产管理员项目详情页 UI 浏览器复测通过：ROO 详情页返回 200，未回登录页，页面包含 `ROO`、`打新成本位`、`自动过滤`，前端 error 数为 0。
