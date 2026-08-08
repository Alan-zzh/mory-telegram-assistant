# dashboard/api 模块规则

## 职责边界
- 本目录是 Dashboard 的 API 层：每个 API 文件对应一个业务面，只做参数校验、鉴权与数据组装，业务逻辑留在 `core/` 与 `modules/`。
- 新增 API 路由必须在 `dashboard/app.py` 注册蓝图，并保持与前端调用契约一致。

## 验收锚点
- 改动后必跑相关单测（`tests/unit/` 下 dashboard 相关用例）。
- 涉及配置项：三处同步（`config.json.example` + 代码 `.get()` 默认值 + Dashboard 白名单），改后跑 `python scripts/check_config_sync.py`。
- 涉及鉴权/审批：遵循 `dashboard/rbac_guard.py` 与 `rbac_approval.py` 的既有边界，不绕过。
