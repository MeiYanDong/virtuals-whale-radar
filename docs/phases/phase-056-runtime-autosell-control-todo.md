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
- [x] 返回当前卖出账本状态，供前端展示已卖出目标、卖出次数和最近卖出时间。

## 3. 执行器

- [x] `launch_sell_executor.py` 支持从 DB 热加载运行时配置。
- [x] 配置缺失时默认阻断真实卖出。
- [x] `enabled=false` 时不卖出。
- [x] `mode=simulate` 时不真实广播。
- [x] 配置版本变化时写入 `sell_config_reloaded` 日志。
- [x] `DualSellConfig` 支持运行时卖出一档/二档比例。

## 4. 前端

- [x] 项目详情页新增管理员专用“自动卖出控制”模块。
- [x] 支持编辑税率窗口、收益率档位、大单档位、卖出比例、冷却时间和事件回看窗口。
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
