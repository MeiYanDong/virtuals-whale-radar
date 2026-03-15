# 管理后台部署与验收记录

## 本地开发

1. 进入 `frontend/admin`
2. 执行 `npm install`
3. 执行 `npm run dev`
4. 默认通过 Vite proxy 转发到 `http://127.0.0.1:8080`

## 构建发布

1. 进入 `frontend/admin`
2. 执行 `npm run build`
3. 构建产物输出到 `frontend/admin/dist/`
4. 启动 Python 服务后，由 `virtuals_bot.py` 暴露：
   - `/admin`
   - `/admin/overview`
   - `/admin/inbox`
   - `/admin/projects`
   - `/admin/wallets`
   - `/admin/operations`
   - `/admin/assets/*`
   - `/admin/brand/*`
5. 旧后台通过 `/dashboard` 保留

## 图标与主题资产

- 根目录 `favicon-vpulse.svg` 已替换为新品牌版本
- `favicon/` 下的 `favicon.ico`、`favicon-16x16.png`、`favicon-32x32.png`、`apple-touch-icon.png`、`android-chrome-*` 已更新
- `site.webmanifest` 已同步新的名称、主题色和背景色
- 新后台品牌资源位于 `frontend/admin/public/brand/`

## 已执行验证

- `npm run lint`
- `npm run build`
- `python -m py_compile virtuals_bot.py signalhub_client.py`
- 隔离端口 `18080` 启动 writer 实例
- 验证 `GET /admin`、`GET /admin/overview`、`GET /dashboard`、`GET /admin/brand/logo-mark.svg`、`GET /favicon/favicon-32x32.png` 返回 `200`
- Playwright 打开并验证：
  - `/admin/overview`
  - `/admin/inbox`
  - `/admin/projects`
  - `/admin/operations`

## 阶段性决策

- `Wallets` 与 `Operations` 已提前进入新后台，不再仅依赖 legacy
- dark mode 评估结论：继续 defer，当前先稳定浅色青绿主题
- 后端 API 重构评估结论：当前通过 adapter 层已足够，暂不拆接口
- 旧 `/dashboard` 下线评估结论：等新后台稳定运行一段时间后再决定
