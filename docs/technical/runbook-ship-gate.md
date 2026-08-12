# Runbook: 改动后验证 + 收工闭环 + 部署门禁（ship-gate）

> 用途：任何部署或代码改动"宣告完成"前，必须过本门禁。证据不足不得宣称完成。

## 最小必查集（按改动类型分组）

### 代码改动：目标测试先行，发布前再扩大
```bash
python -m pytest <相关测试> -q                      # 必跑：真实受影响链
python -m compileall <受影响目录或文件> -q          # 必跑：语法兜底
# 待部署、高风险、跨模块或公共基础设施改动再跑：
python -m pytest tests/unit/ -q
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

| 文件 | 关键函数 | 测试锚点 |
|---|---|---|
| `core/ai_engine.py` | `_get_dynamic_llm_params` / `_select_emotion_bucket` | `tests/unit/test_v5_19_0_persona_engine.py` |
| `core/ai_engine.py` | `_sanitize_reply_v2` | `tests/unit/test_ai_engine_resilience.py`、`tests/unit/test_full_persona_tone_contract.py` |
| `modules/auto_tasks.py` | 问候/定时任务配置函数 | `tests/unit/test_auto_tasks_greeting_config.py`；播报任务另见 `tests/unit/test_scheduled_broadcast_rich.py` |
| `core/database.py` | `DB.__init__` / `reconnect` / `_safe_add_column` | `tests/unit/test_v5_35_0_fixes.py` |
| `modules/ad_detector.py` | `AdDetector` / `check_username_suspicious` / `SCORE_THRESHOLD` | `tests/unit/test_ad_detector_core.py` |
| `modules/admin_cmds.py` | `_parse_feed_scene` / `_parse_and_feed_pairs` | `tests/unit/test_feed_sample_command.py` |
| `dashboard/app.py` | `create_app` | `tests/unit/test_dashboard_app_smoke.py` |
| `dashboard/templates/html_page.py` | （暂无锚点，按受影响 API + Dashboard smoke 兜底） | 待补：新增函数测试后登记 |
| `tasks/broadcast/greeting_task.py` | `GreetingTask`（问候/文案随机化） | `tests/unit/test_night_greeting_schedule.py`；随机文案另见 `tests/unit/test_scheduled_broadcast_rich.py` |
| `tasks/broadcast/mystic_broadcast_task.py` | `build_mystic_cta` / `MysticBroadcastTask` | `tests/unit/test_mystic_broadcast.py` |
| `tasks/support/mystic_content.py` | `build_mystic_broadcast` / `resolve_private_mystic_mode` | `tests/unit/test_mystic_broadcast.py` |

改动锚点外函数时先按调用链选择目标测试；待部署、高风险或跨模块变更再跑全仓 unit。新增公共行为后必须补测试锚点，表内不记录易漂移行数。

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

日志通道与保留策略会随部署配置变化，排查时必须读当前 logging 配置、实际 `logs/` 和 journald，不能根据文档假定文件日志一定存在或覆盖完整窗口。

排查或诊断前先确认可回溯性：

```bash
systemctl status mory-assistant --no-pager | head -20        # 确认 NRestarts 等状态
journalctl -u mory-assistant --since "today" --no-pager | tail -50   # 确认日志可用
# 若 journal 被清：记录 evidence_gap；NRestarts=0 和 health 200 只能证明当前存活，不能反推窗口内无错误
```

归档策略（VPS 侧变更需生产部署授权后执行）：
- journald 持久化：`journalctl --vacuum-size` / `--vacuum-time` 设置保留上限，避免无界占用；确认清理责任方（系统自动清理 vs 外部脚本）。
- 文件通道：将 `logs/` 轮转文件纳入归档任务（如每日打包至备份目录），保留窗口覆盖最近一次发版周期。
- 完成后用一次已知事件（按 msg_id/request_id）验证跨边界回溯链可用。

## 部署完成判据（按受影响面取证，未拿到不得宣称完成）
```bash
systemctl show mory-assistant mory-dashboard -p ActiveState -p MainPID -p NRestarts
curl -sS -w '\nHTTP=%{http_code}\n' localhost:6616/api/health
cd /home/ubuntu/mory_assistant && /usr/bin/python3 -c 'from version import VERSION; print(VERSION)'
stat -c '%U:%G %a %n' /etc/systemd/system/mory-*.service
# VPS 版本/受影响文件 hash == 本地预期；health 不提供版本证据
# 新 PID 启动窗口无未解释 ERROR/CRITICAL，历史窗口缺失必须标 evidence_gap
# 受影响业务入口完成真实探针；调度改动另附当前执行证据 + task_execution_history 四态和 coverage
```

判读规则：`health 200` 只是 liveness；`scheduler_metrics` 是历史指标而非当前注册表；`task_execution_history` 只覆盖事务审计任务。任何一项绿色都不能覆盖真实业务失败。

## 收工闭环
文档触发条件和统一完成回执只由 `AGENTS.md` B 节定义，本 runbook 不复制第二份。达到触发条件须同会话更新，未达到则不写。

**部署三选一（收工必填，未填视为未完工）**：`已部署`（附验证输出）/ `无需部署`（写明理由）/ `门禁阻断`（写明阻断项）。

## 证据要求
按 `AGENTS.md` 的七项统一回执输出；影响生产行为的改动必须包含本节部署判据和受影响业务探针，估算不得冒充真实收益。
