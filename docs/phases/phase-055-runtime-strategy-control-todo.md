# Phase 055 Runtime Strategy Control Todo

## 1. 文档

- [x] 新增 Phase 055 子 plan。
- [x] 新增 Phase 055 子 todo。
- [x] 更新 `docs/PLAN.md`。
- [x] 更新 `docs/todo.md`。
- [x] 更新 `docs/plan-index.md`。
- [x] 更新 `docs/todo-index.md`。

## 2. 后端

- [x] 新增运行时策略配置表。
- [x] 新增配置修改审计表。
- [x] 新增管理员读取配置 API。
- [x] 新增管理员保存配置 API。
- [x] 校验基础买入、抄底买入、单笔上限和项目预算。
- [x] 返回当前已发送买入 V，防止预算下调到已执行金额以下。

## 3. 执行器

- [x] `launch_prewarm_executor.py` 支持从 DB 热加载运行时配置。
- [x] 配置缺失时沿用 CLI/systemd 默认值。
- [x] `enabled=false` 时不发出 BuyIntent。
- [x] `mode=simulate` 时不真实广播。
- [x] 配置版本变化时写入 `strategy_config_reloaded` 日志。
- [x] 2026-05-20 新增含税估算 FDV 限价运行时配置：默认关闭，开启后作为原有入场条件之后的额外保险门槛。

## 4. 前端

- [x] 项目详情页新增管理员专用“自动买入控制”模块。
- [x] 支持编辑基础买入、抄底买入、抄底阈值、横盘暂停阈值、单笔上限和项目预算。
- [x] 支持保存 simulate 配置。
- [x] 支持启用 broadcast 配置。
- [x] 展示配置版本、修改时间和已买入 V。
- [x] 优化“自动买入控制”模块 hover / focus 动效，提升发射窗口内的操作反馈。
- [x] 收敛管理员交互：隐藏原生执行字段，移除模式/修改原因输入，只保留恢复默认、保存并启用、停用自动买入。
- [x] 参数默认显示去掉无意义小数。
- [x] 把单位放回字段内展示，并为“抄底阈值”“横盘跳过”补充和成本位一致的信息图标解释。
- [x] 保存/停用前自动保证单笔上限不低于基础买入和抄底买入，并把后端原生字段错误转成中文业务提示。
- [x] 2026-05-20 前端新增“估算市值限价”卡片：管理员可输入最高含税 FDV（万 USD），并独立开启/关闭。

## 5. 验证

- [x] `.venv/bin/python -m py_compile virtuals_bot.py scripts/ops/launch_prewarm_executor.py scripts/ops/launch_execution_pipeline.py scripts/ops/test_launch_execution_pipeline.py scripts/ops/test_launch_prewarm_executor.py`。
- [x] `.venv/bin/python scripts/ops/test_launch_execution_pipeline.py`。
- [x] `.venv/bin/python scripts/ops/test_launch_prewarm_executor.py`。
- [x] `npm run build`。
- [x] `npm run lint`。
- [x] 本地管理员页面浏览器烟测：`/admin/projects/1?project=TDS` 可渲染“自动买入控制”，默认与热门预设可见。
- [x] 本地 HTTP 保存烟测：POST simulate `100/200/200/300` 成功后重置为 disabled `25/50/50/150`。
- [x] 2026-05-16 生产网页真实保存探针：`/admin/projects/15?project=ROO` 输入 `0.002/0.003` 后 POST 成功，API 回读 `enabled=true / mode=broadcast`，随后页面停用。
- [x] 2026-05-16 生产 DB 探针：保存后 `launch_strategy_runtime_configs` 立即写入对应值；测试后已清理 ROO 探针配置行。
- [x] 2026-05-16 执行器热读取探针：临时写入 `0.004/0.005` 后，`launch_prewarm_executor.py --once --mode simulate` 记录 `hasOverride=true / version=1`；ROO 已 ended，因此正确输出 `not_live` 且 `tradeSent=false`。
- [x] 新增 `scripts/ops/runtime_control_launch_simulator.py`，用于本地 paper replay 验证前端运行时参数在后续发射 tick 中被执行器热读。
- [x] 2026-05-18 本地网页保存 TDS 小额参数 `0.1/0.2/0.2/0.6` 后，后端回读 `enabled=true / mode=broadcast / version=22`。
- [x] 2026-05-18 TDS 100x 完整窗口模拟通过：99 个 tick 约 1 分钟跑完，产生 `0.1/0.2/0.1/0.2 VIRTUAL` 四次 paper buy intent，项目预算 `0.6 VIRTUAL` 生效后阻断后续意图。
- [x] 2026-05-18 模拟完成后停用本地 TDS 自动买入，回读 `enabled=false / mode=simulate / version=23`。
- [x] 2026-05-18 历史样本驱动真实 canary 通过：sample `30` 运行中改买入参数后记录 `strategy_config_reloaded`，sample `55` / tax `95%` 自动买入使用更新后的 `0.01 VIRTUAL`，tx `0x541481388328fb7a8181b05ed749518c0fffc605b05badada5b5a8db584062e5`，receipt `0x1`。
- [x] 2026-05-20 限价配置本地验证通过：`py_compile`、`test_launch_execution_pipeline.py`、`test_launch_prewarm_executor.py`、前端 `npm run build`。
