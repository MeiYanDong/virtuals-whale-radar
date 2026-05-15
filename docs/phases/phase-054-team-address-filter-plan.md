# Phase 054 Team Address Filter Plan

## 1. 目标

保持大户榜单整洁：自动识别疑似团队/初始低成本地址并默认排除出打新成本位；管理员能查看被过滤的钱包，并对单个地址做手动排除或手动纳入。

## 2. 非目标

- 不接真实交易。
- 不改变历史原始 leaderboard 数据。
- 不删除链上事件、分钟聚合或钱包持仓记录。
- 不让普通用户操作团队地址过滤。

## 3. 规则优先级

1. 管理员手动排除：最高优先级，命中后不计入成本位。
2. 管理员手动纳入：覆盖自动识别，重新计入成本位。
3. 自动识别：没有人工覆盖时，按现有开盘极早期、低税/无税、大额低成本占比异常规则标记为疑似团队。
   - 首分钟零税且当时预期应有税的钱包直接自动过滤，不要求买入份额达到阈值。
   - Phase 053 追加高置信规则：如果某钱包的买入交易命中团队/初始化路径，应直接自动过滤。
     - `tx.to == 0x1a540088125d00dd3990f9da45ca0859af4d3b01`
     - `selector == 0x214013ca`
   - 该规则比单纯“首分钟零税”更强，因为它来自交易入口语义：普通用户 direct buy 是 `0x706910ff`，团队/初始化交易是 `0x214013ca`。
   - `tax_v == 0` 和发射早期窗口只作为回放验证现象，不进入最终判断条件，避免冗余。
   - 当前生产事件表尚未持久化交易 selector；上线该规则前，需要在采集/回填阶段保存 `tx_to / tx_selector / calldata_bytes`，或建立按 `tx_hash` 的 route classification 缓存表。

## 4. 后端设计

- 新增 `team_address_overrides` 表，按 `project + wallet` 保存管理员覆盖规则。
- 新增管理员 API：
  - `POST /api/admin/projects/{project_id}/team-address-overrides`
  - `DELETE /api/admin/projects/{project_id}/team-address-overrides/{wallet}`
- overview 聚合返回每个榜单地址的：
  - `isTeamCandidate`
  - `costExcluded`
  - `costExclusionReason`
  - `teamOverrideAction`
  - `teamOverrideReason`
  - `teamOverrideUpdatedAt`

## 5. 前端设计

- 主大户榜单只展示 `costExcluded=false` 的地址。
- 主大户榜单不展示团队地址，也不展示“团队过滤”操作列。
- 管理员额外看到唯一的默认折叠“小型自动过滤”控件：
  - 自动识别和手动排除的钱包不在主大户榜单展示。
  - 管理员按需展开自动过滤控件查看隐藏地址。
  - 管理员可输入钱包地址和备注，加入排除。
  - 管理员可点击“纳入成本位”，把地址移回主榜单计算。
- 普通用户不展示过滤审核操作。

## 6. 验收标准

- 自动识别的疑似团队地址不参与打新成本位计算。
- 手动排除能立即把榜单内地址移到审核区。
- 手动纳入能覆盖自动识别并恢复成本位计算。
- 手动输入暂未进入 Top20 的地址时，覆盖规则先保存；后续进入榜单后生效。
- 本地 `py_compile`、前端 build、lint 通过。
- 本地 API 与前端 UI 流程通过。
- `0x81f7ca6af86d1ca6335e44a2c28bc88807491415` 这类首分钟零税且当时预期应有税的地址会自动过滤。
- `0x81f7ca6af86d1ca6335e44a2c28bc88807491415` 在 SR/ISC/TDS 样本中同时命中团队/初始化 selector `0x214013ca`，后续应作为更高置信自动过滤依据。

## 7. 当前状态

- 2026-05-07：本地实现并通过验证。
- 2026-05-15：代码已随生产部署进入远端；生产服务健康。具体部署 commit 以服务器 `DEPLOYED_COMMIT` 为准。
- 生产 overview API 烟测已通过：ROO overview 返回 `ok=true`、`whaleBoard=20`、`trackedWallets=6`、`hiddenTeamRows=1`。
- 仍需生产管理员项目详情页 UI 浏览器复测。
- 已接入更高置信的团队/初始化 route 自动过滤：事件入库持久化 `tx_to / tx_selector / calldata_bytes`，`selector == 0x214013ca` 直接作为疑似团队/初始化购买信号。
- SR/ISC/TDS 回放验证已完成：`0x214013ca` 均命中 `0x81f7ca6af86d1ca6335e44a2c28bc88807491415`，普通 `0x706910ff` direct buy 不误杀；报告见 `docs/phases/phase-054-route-filter-validation-2026-05-15.md`。
