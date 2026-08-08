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

### 巨型核心文件 → 针对性测试锚点映射表
改动巨型热文件时，按受影响函数直接定位对应测试，避免通读整份文件：

| 文件（行数） | 关键函数 | 测试锚点 |
|---|---|---|
| `core/ai_engine.py`（约 2800+ 行） | `_get_dynamic_llm_params` / `_select_emotion_bucket` | `tests/unit/test_v5_19_0_persona_engine.py` |
| `core/ai_engine.py` | `_sanitize_reply_v2` | `tests/unit/test_ai_engine_resilience.py`、`tests/unit/test_full_persona_tone_contract.py` |
| `modules/auto_tasks.py`（4300+ 行） | 问候/定时任务配置函数 | `tests/unit/test_auto_tasks_greeting_config.py`；播报任务另见 `tests/unit/test_scheduled_broadcast_rich.py` |
| `core/database.py`（约 2300 行） | `DB.__init__` / `reconnect` / `_safe_add_column` | `tests/unit/test_v5_35_0_fixes.py` |
| `modules/ad_detector.py`（2100+ 行） | `AdDetector` / `check_username_suspicious` / `SCORE_THRESHOLD` | `tests/unit/test_ad_detector_core.py` |
| `modules/admin_cmds.py` | `_parse_feed_scene` / `_parse_and_feed_pairs` | `tests/unit/test_feed_sample_command.py` |
| `dashboard/app.py` | `create_app` | `tests/unit/test_dashboard_app_smoke.py` |
| `dashboard/templates/html_page.py`（5100+ 行） | （暂无锚点，按全仓 unit 兜底） | 待补：新增函数测试后登记 |
| `tasks/broadcast/greeting_task.py` | `GreetingTask`（问候/文案随机化） | `tests/unit/test_night_greeting_schedule.py`；随机文案另见 `tests/unit/test_scheduled_broadcast_rich.py` |
| `tasks/broadcast/mystic_broadcast_task.py` | `build_mystic_cta` / `MysticBroadcastTask` | `tests/unit/test_mystic_broadcast.py` |
| `tasks/support/mystic_content.py` | `build_mystic_broadcast` / `resolve_private_mystic_mode` | `tests/unit/test_mystic_broadcast.py` |

改动锚点外函数时仍按最小必查集跑全仓 unit；新增函数改动后必须在本表补充或更新锚点行。

### 变更→验证绑定（每次改动必填，写入 commit 验收证据）
每次改动在收工前记录受影响测试、实际运行的验证命令与结果摘要，随 commit 一并提交；禁止以全仓 unit 通过代替受检路由：

| 改动文件 | 受影响测试/关键函数 | 验证命令 | 结果摘要 |
|---|---|---|---|
| `<文件路径>` | `<锚点测试或关键函数>` | `python -m pytest <锚点测试> -q` | `<通过数> passed / 失败项>` |

绑定规则：有锚点 → 先跑锚点测试再跑最小必查集；无锚点 → 按受影响模块筛选相关测试并记录；结果摘要必须含失败项与修复后复验。

## 部署前置门禁（任一失败 → 停止、不部署）

1. **Git 卫生**：`git status --porcelain` 输出为空或已 commit；脏工作树禁止部署。
2. **版本一致**：`version.py` == `VERSION.md` 首行 == 本次期望版本（bump 与代码改动同 commit，禁止部署后才发现版本未同步）。
3. **清单完整**：增量清单必须含 `version.py` 与本次涉及的非 `.py` 资源（新增目录/字体/图片）。
4. **门禁脚本**：`verify_db_methods.py` / `doc_consistency.py` 通过；配置改动另加 `check_config_sync.py`。

一键检查：`python scripts/check_deploy_ready.py`（合并以上 1/2/4 为一条命令）。

## 生产日志保留与归档（排查前必读）

日志双通道：文件轮转（`core/logging_util.py`：RotatingFileHandler，10MB × 5 份）+ systemd journald（stdout 捕获）。两者均无归档策略；journald 可能被外部清理导致历史事件无法回溯（窗口内已发生）。

排查或诊断前先确认可回溯性：

```bash
systemctl status mory-assistant --no-pager | head -20        # 确认 NRestarts 等状态
journalctl -u mory-assistant --since "today" --no-pager | tail -50   # 确认日志可用
# 若 journal 被清：以 NRestarts=0 + health 200 佐证健康，并记录"日志不可回溯"到排查结论
```

归档策略（VPS 侧变更需生产部署授权后执行）：
- journald 持久化：`journalctl --vacuum-size` / `--vacuum-time` 设置保留上限，避免无界占用；确认清理责任方（系统自动清理 vs 外部脚本）。
- 文件通道：将 `logs/` 轮转文件纳入归档任务（如每日打包至备份目录），保留窗口覆盖最近一次发版周期。
- 完成后用一次已知事件（按 msg_id/request_id）验证跨边界回溯链可用。

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
