# 阶段 1+2：全面体检问题清单

**日期**：2026-07-20
**方式**：2 个 subagent 并行静态扫描 + 主代理验证
**基于代码版本**：v5.35.2

---

## P0 问题（5 个，必修，启动/启用即崩）

| ID | 文件:行号 | 问题 | 证据 | 修复 |
|----|-----------|------|------|------|
| P0-01 | `modules/stats_report.py:67` | `cursor.fetchone()[0] if cursor.fetchone() else 0` 两次调用 fetchone()，`active_members` 永远为 0 | 已 Read 验证：第 67 行确为此代码 | `row = cursor.fetchone(); active_members = row[0] if row else 0` |
| P0-02 | `modules/stats_report.py:93` | 同 P0-01 模式，`recent_messages` 永远为 0 | 已 Read 验证：第 93 行确为此代码 | 同 P0-01 |
| P0-03 | `modules/valid_speak.py:66` | 第 5 行 `from datetime import datetime` 缺 `timedelta`；第 66 行 `timedelta(days=days)` 必 NameError | 已 Read 验证 | 第 5 行改 `from datetime import datetime, timedelta` |
| P0-04 | `tasks/maintenance/log_cleanup_task.py:43` | 第 7-12 行 import 无 `os`；第 43 行 `os.path.dirname(...)` 必 NameError，每天 04:00 触发即崩 | 已 Read 验证 | import 区添加 `import os` |
| P0-05 | `modules/security_center.py:126` | `eval(row[1])` 任意代码执行风险，row[1] 来自数据库 `user_risk_profile.risk_factors` 字段 | 已 Read 验证 | 改 `json.loads(row[1]) if row[1] else {}` + 写入用 `json.dumps` |

**文档失真纠正**：
- `AI_DEBUG_HISTORY.md` #16 声称"v5.35.2 修复 stats_report 8 处 fetchone" — **实测只修了 6 处，仍剩 2 处**（P0-01、P0-02）
- `AI_DEBUG_HISTORY.md` #17 声称"valid_speak.py timedelta 已修复" — **实测只改了用法，未补 import**（P0-03）

## P1 问题（9 个，应修，功能错误/资源风险）

| ID | 文件:行号 | 问题 | 修复 |
|----|-----------|------|------|
| P1-01 | `dashboard/api/settings_api.py:22` | `logger` 未定义，触发 NameError | 添加 `from core.logging_util import get_logger; logger = get_logger("settings_api")` |
| P1-02 | `modules/group_props.py:122-123` | `unmute` 效果缺 `hasattr` 防御（其他 3 个效果都有） | 加 `if hasattr(self._compat, 'unban_chat_member'):` 防御 |
| P1-03 | `modules/group_migration.py:77-89` | SELECT 无 WHERE + INSERT OR REPLACE 无 id，数据无限增长且只读首行 | 加 `WHERE id=1` + `INSERT OR REPLACE (id, data) VALUES (1, ?)` |
| P1-04 | `modules/group_report.py:96` | 同步方法 `process_report_action` 调用 `_compat.send_message`（可能为 coroutine） | 验证 _compat.send_message 是否为 async，必要时改 async |
| P1-05 | `modules/crypto_detector.py:66` | 绕过 `core/http_client.py` 直连 `requests.get` | 改用 `core.http_client.HTTPClient` |
| P1-06 | `modules/group_migration.py:107-108` | `except Exception: pass` 静默吞错 | 改 `except Exception as e: logger.warning(...)` |
| P1-07 | `core/ai_engine.py:2311-2312` | `time.sleep(2^x)` 同步阻塞主线程，最长 8s | 评估后改 `asyncio.sleep` 或保留（已有 max_attempts=3 限制） |
| P1-08 | `core/bot_initializer.py:804` | `_restore_db_from_backup` 中 `db.close()` 后调用 `_load_dynamic_states(cfg, db)` | 调换顺序或重新打开 db |
| P1-09 | `core/message_dispatcher.py:185-186` | `except Exception: logger.debug(...)` 静默吞错 | 改 `logger.warning` |

## P2 问题（19 个，建议修）

| ID | 文件:行号 | 问题 | 修复 |
|----|-----------|------|------|
| P2-01 | `core/ai_engine.py:1622-1623` | `except Exception: pass` 静默吞错 | 改 `logger.debug` |
| P2-02 | `core/ai_engine.py:74-75, 119-120, 210-211, 1831-1832` | 多处 `except Exception: pass` | 改 `logger.debug` |
| P2-03 | `main.py:68-69` | `except Exception: pass` 静默吞错 | 改 `logger.debug` |
| P2-04 | `modules/ad_enforcement.py:136,263,388,403` | 多处 `except Exception: pass` | 黑名单写入失败应 `report_fault` |
| P2-05 | `modules/managed_groups.py:152-153` | `except Exception: pass` | 改 `logger.warning` |
| P2-06 | 根目录 11 个 `_tmp_*.py` | 临时调试文件污染根目录 | 移到 `runtime/_tmp/` 或删除（先验证 .gitignore 已覆盖） |
| P2-07 | `scripts/vps_delete_ads_by_range.py:129` | 硬编码 chat_id 8012433255 | 改 `os.environ.get('TARGET_CHAT_ID')` |
| P2-08 | `scripts/vps_*.py` 多文件 | 硬编码 user_id 153196034/698678153 | 移到 .env |
| P2-09 | `migrations/versions/0001_initial_schema.py` | upgrade()/downgrade() 均 pass，Alembic 无实际迁移能力 | 补全或明确注释 baseline-only |
| P2-10 | `core/message_dispatcher.py:59-63` | 已注释死代码 `# _append_pool = ...` | 删除 |
| P2-11 | `modules/auto_tasks.py:446, 4928` | legacy `while True:` 循环 | 标记 `# DEPRECATED` 或删除 |
| P2-12 | `core/router_database.py:47-52, 60` | `threading.local()` 存连接，shutdown 时其他线程连接无主动关闭 | 维护线程→连接映射 |
| P2-13 | `dashboard/app.py:149-150` | `except Exception: pass` | 改 `logger.debug` |
| P2-14 | `core/bot_initializer.py:564` | 启动期同步 `bot.get_me()` 阻塞主线程 | 加超时 + 失败明确退出 |
| P2-15 | `core/bot_initializer.py:663-666` | 启动期同步 `ad_detector.process_pending_bans` 阻塞 | 改 daemon 线程异步 |
| P2-16 | `core/bot_initializer.py:626-627` | `mark_replied` 每次回复查 DB，无缓存 | 引入内存计数 + 周期 flush |
| P2-17 | `modules/stats_report.py:101-110` | `get_activity_stats` for 循环内逐小时 SQL，N+1 查询 | 改单条 `GROUP BY hour` |
| P2-18 | `deploy_vps.py:417-475` | 部署失败无回滚机制 | 增加 git reset 回滚 |
| P2-19 | `start_dashboard.py:41` | 临时密码明文打印到 stdout | 改掩码 `pwd[:4]...pwd[-4:]` |

## P3 问题（10 个，可选）

| ID | 文件:行号 | 问题 | 修复 |
|----|-----------|------|------|
| P3-01 | `modules/bottom_button.py:53` | `InlineKeyboardButton` 同时传 `url=''` 和 `callback_data=''` 空串 | 仅传非空字段 |
| P3-02 | `config.json.example:2` | `_CONFIG_VERSION=5.35.0` vs version.py 5.35.2 | 改 5.35.2 |
| P3-03 | `core/deploy_utils.py:313` | API key 打印前 12 位（偏多） | 改前 6 位 |
| P3-04 | `scripts/check_token.py:10,14` | 明文打印 BOT_TOKEN | 删除 + 改前 6 后 4 |
| P3-05 | `scripts/bruteforce_delete.py:19` | 打印 token 前 10 位 | 改前 6 位 |
| P3-06 | `docs/technical/capability-matrix.md:6-7` | 文档数字过期（83 modules/96 routes vs 实际 135/157） | 更新或归档 |
| P3-07 | `scripts/vps_check_logs.py:14` | 硬编码用户 ID | 参数化 |
| P3-08 | `scripts/vps_delete_ads_quick.py:64` | 硬编码用户 ID | 参数化 |
| P3-09 | `modules/group_migration.py:78` | SELECT 无 LIMIT 1 | 加 LIMIT 1 |
| P3-10 | `core/message_dispatcher.py:54-57` | `_radar_cooldown` 无上限 | 加 MAX 限制 |

---

## 汇总

| 严重度 | 数量 |
|--------|------|
| P0 | 5 |
| P1 | 9 |
| P2 | 19 |
| P3 | 10 |
| **总计** | **43** |

## 修复策略

1. **阶段 4 第一批**：所有 5 个 P0（启动/启用即崩）
2. **阶段 4 第二批**：P1-01, P1-02, P1-03, P1-06（4 个低风险高收益）
3. **阶段 4 第三批**：P2-06（11 个 _tmp_*.py 清理）+ P2-19（密码掩码）+ P3-02（版本号同步）
4. **阶段 4 第四批**：P2-01~P2-05, P2-13（静默吞错改为 logger.debug/warning）
5. 其余 P2/P3 标记为"后续处理"，不影响稳定性
