# Runbook: 改动后验证 + 收工闭环 + 部署门禁（ship-gate）

> 用途：任何部署或代码改动"宣告完成"前，必须过本门禁。证据不足不得宣称完成。

## 最小必查集（按改动类型分组）

### 代码改动必跑
```bash
python -m pytest tests/unit/ -q                    # 相关测试 + 全仓 unit
python -m compileall core/ modules/ dashboard/ -q  # 语法兜底
flake8 core/ai_engine.py core/settings.py core/database.py core/user_lifecycle.py \
       core/metrics.py core/anomaly_detector.py dashboard/app.py dashboard/api/metrics_api.py \
       --ignore=E501,W503,W504,E203,E402 --max-line-length=120   # 8 文件 CI 清单
mypy core/settings.py core/database.py core/ai_engine.py core/user_lifecycle.py --follow-imports=silent
```

### 数据库改动必跑（在代码改动之上）
```bash
python scripts/verify_db_methods.py   # 新增 Repo 方法必须注册 _REPO_METHOD_MAP/_REPO_ATTR_MAP
# + 读写往返测试（write → read → assert，禁止只跑 import）
# + schema 改动同步 Alembic migration，部署后验证表结构
```

### 配置改动必跑
```bash
python scripts/check_config_sync.py   # example ↔ Dashboard 白名单差集断言
# + 无 example 时的代码 .get() fallback 行为回归
```

### 文档改动必跑
```bash
python scripts/doc_consistency.py     # METRICS + 版本五源一致 + 行数 + CHANGELOG 条目长度断言
```

## 部署前置门禁（任一失败 → 停止、不部署）

1. **Git 卫生**：`git status --porcelain` 输出为空或已 commit；脏工作树禁止部署。
2. **版本一致**：`version.py` == `VERSION.md` 首行 == 本次期望版本（bump 与代码改动同 commit，禁止部署后才发现版本未同步）。
3. **清单完整**：增量清单必须含 `version.py` 与本次涉及的非 `.py` 资源（新增目录/字体/图片）。
4. **门禁脚本**：`verify_db_methods.py` / `doc_consistency.py` 通过；配置改动另加 `check_config_sync.py`。

一键检查：`python scripts/check_deploy_ready.py`（合并以上 1/2/4 为一条命令）。

## 部署完成判据（缺一不可，未拿到不得宣称完成）
```bash
systemctl status mory-assistant mory-dashboard --no-pager   # 均 active
curl -s -o /dev/null -w '%{http_code}\n' localhost:6616/api/health   # 200
# VPS 端 version.py == 本地 version.py（禁止用 health 版本号单独冒充完整部署）
# 当前进程日志无新增 ERROR + 最小真实业务回执（发送/触发证据）
```

## 收工闭环（触发式文档更新，替代旧"六件套"）
按 AGENTS.md B 节触发条件更新文档，未达条件不写；达到条件同会话内完成，禁止"下次再补"：
- `CHANGELOG.md`：仅用户可感知改动（升版/事故修复/配置或部署变化），一行 ≤100 字，验收证据写 commit message。
- `project_snapshot.md`：METRICS / 模块状态 / 发布变化，覆盖式，最近大事 ≤3 条。
- `AI_DEBUG_HISTORY.md`：反复暗病 ≥2 次 / 结构风险 / 生产事故根因，单条 ≤200 字。
- `VERSION.md`：仅升版时（与 `version.py` 同步）。
- `README.md` / `AGENTS.md`：入口或规则变化时。

**部署三选一（收工必填，未填视为未完工）**：`已部署`（附验证输出）/ `无需部署`（写明理由）/ `门禁阻断`（写明阻断项）。

## 证据要求
至少两条：修改文件 + diff 摘要 / 命令输出 / 测试结果；影响生产行为的改动必须含部署完成判据证据。
