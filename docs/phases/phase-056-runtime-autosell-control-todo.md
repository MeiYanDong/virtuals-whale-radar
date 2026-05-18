# Phase 056 Runtime Autosell Control Todo

## 1. 文档

- [x] 新增 Phase 056 子 plan。
- [x] 新增 Phase 056 子 todo。
- [x] 更新 `docs/PLAN.md`。
- [x] 更新 `docs/todo.md`。
- [x] 更新 `docs/plan-index.md`。
- [x] 更新 `docs/todo-index.md`。
- [x] 更新 `scripts/ops/deploy_production_safe.sh` 同步清单。

## 2. 后端

- [x] 新增 `launch_sell_runtime_configs` 表。
- [x] 新增 `launch_sell_runtime_config_audit` 审计表。
- [x] 新增管理员读取自动卖出配置 API。
- [x] 新增管理员保存自动卖出配置 API。
- [x] 校验税率窗口、收益率档位、大单档位、卖出比例、冷却时间和事件回看窗口。
- [x] 新增 `custom_rules_json`，支持条件组合式白名单卖出规则。
- [x] 兼容旧的限价卖出、大单卖出、高收益率卖出、收益率 + 大单配置，并在保存时归一化为条件组。
- [x] 自定义规则保存前完成类型、单位、阈值和卖出比例校验；无效配置不会覆盖当前有效配置。
- [x] 返回当前卖出账本状态，供前端展示已卖出目标、卖出次数和最近卖出时间。

## 3. 执行器

- [x] `launch_sell_executor.py` 支持从 DB 热加载运行时配置。
- [x] 配置缺失时默认阻断真实卖出。
- [x] `enabled=false` 时不卖出。
- [x] `mode=simulate` 时不真实广播。
- [x] 配置版本变化时写入 `sell_config_reloaded` 日志。
- [x] `DualSellConfig` 支持运行时卖出一档/二档比例。
- [x] `CustomSellConfig` 支持 `condition_group`，一条规则内部可选择 `AND / OR`。
- [x] 多规则同时触发时按规则增量累加，但总卖出不超过原始仓位 `100%`，且不超过当前钱包余额。
- [x] 大单规则按 `rule_id + tx_hash` 去重，避免同一笔大单重复触发同一条规则。
- [x] 规则解析异常只跳过无效规则，不影响执行器继续运行。

## 4. 前端

- [x] 项目详情页新增管理员专用“自动卖出控制”模块。
- [x] 支持编辑税率窗口、收益率档位、大单档位、卖出比例、冷却时间和事件回看窗口。
- [x] 支持前端用规则构建器配置价格、大单、收益条件，并选择 `AND / OR`。
- [x] 默认推荐规则为“收益率 >= 30% AND 单笔买入 >= 5000 VIRTUAL，卖出 30%”。
- [x] 大单门槛单位支持 `VIRTUAL / USD`，限价单位支持 `USD / VIRTUAL`。
- [x] 展示配置版本、已卖出目标、卖出次数和最近卖出时间。
- [x] 前端收敛为 `恢复默认`、`保存并启用`、`停用自动卖出`，隐藏 mode/updatedReason 等原生字段。
- [x] 使用中文业务错误提示，避免暴露后端原生字段。

## 5. 验证

- [x] `.venv/bin/python -m py_compile virtuals_bot.py scripts/ops/launch_sell_strategy.py scripts/ops/launch_sell_executor.py scripts/ops/test_launch_execution_pipeline.py scripts/ops/test_launch_sell_executor.py`。
- [x] `.venv/bin/python scripts/ops/test_launch_execution_pipeline.py`。
- [x] `.venv/bin/python scripts/ops/test_launch_sell_strategy.py`。
- [x] `.venv/bin/python scripts/ops/test_launch_sell_executor.py`。
- [x] `npm run build`。
- [x] `npm run lint`。
- [x] 本地执行器热加载探针：通过管理员 API 保存探针配置后，`launch_sell_executor.py` 记录 `sell_config_reloaded`，随后可恢复 disabled 默认配置。
- [x] 2026-05-18 历史样本驱动真实 canary 通过：sample `700` 运行中启用自动卖出后记录 `sell_config_reloaded`，sample `819` / tax `30%` 自动卖出本次 TDS 持仓，tx `0xce9d5637f82894ef2bfd2dc403664b6f143ba58b943ac3d0c7fc322fb8c47b0a`，receipt `0x1`；测试后 TDS 余额与 sell allowance 均为 `0`。
- [x] 2026-05-18 远端漂移验证：生产库缺少 `custom_rules_json` 会导致自定义卖出规则无法热加载触发；已同步 `virtuals_bot.py` 并运行 Storage migration 补齐字段。
- [x] 2026-05-18 远端 TDS / VOID 历史样本 canary 通过：sample `700` 写入卖出配置、sample `819` / tax `30%` 自动卖出，最终 token 余额 `0`、active fuse `0`。
