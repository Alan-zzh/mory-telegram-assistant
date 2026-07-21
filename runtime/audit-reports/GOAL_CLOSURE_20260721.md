# v5.35.5 整仓修复与生产闭环报告

> 日期：2026-07-21
> 当前判定：`VERIFIED_CLOSED`
> 完成依据：可信 Git commit、最小生产发布、重启后多真相面复验均已完成。

## 1. 结论

本轮不是复述旧报告，而是重新以当前工作树、隔离环境和 VPS 为真相面执行验收。已确认并修复三类真实漂移：

1. Git `main` 中 4 个已修模块被一次 VPS→本地反向同步覆盖回断链实现；生产文件反而保持正确。
2. 生产外部 watchdog cron 消失约 12 天，但旧 loop-monitor 仍输出 `all normal`。
3. 本地 `.venv` 是无 pip/依赖的 Python 3.14 空环境，未跟踪 `uv.lock` 也没有项目依赖；README 口径失真。

本地修复已提交到 `main`（`18e048e`、`a71141c`），生产采用最小边界发布 `version.py` 与 `scripts/puzan_loop_monitor.py`，四个业务模块以源码内容核验对齐；重启后版本、服务、日志、watchdog 与业务调度均形成成功回执。本轮状态可判定为 `VERIFIED_CLOSED`。

## 2. 修复范围

| 范围 | 修复内容 | 证据 |
|------|----------|------|
| 模块回归 | 恢复 `anti_raid`、`group_members`、`punishment_center`、`crypto_detector` 正确实现 | 50 个历史回归测试全过；与生产源码内容一致，3 个文件仅 EOF 换行字节不同 |
| 监控真实性 | `EXPECTED_VERSION` 改从 `version.py` 读取；L1-L6 任一非 OK 均进入 NEEDS_REVIEW；cron 缺失显式 WARN | 新增 5 个监控/Windows 门禁测试；真实探针能识别本地/生产版本不一致 |
| Windows 门禁 | DB 注册脚本稳定输出 UTF-8；`alembic.ini` 改为 locale 安全注释 | 非 UTF-8 子进程测试与 `alembic heads/current` 通过 |
| 环境可复现 | 生成 94 个精确包、2406 个 SHA-256 hashes 的 `requirements.lock`；重建 Python 3.12 `.venv` | `pip install --require-hashes`、`pip check` 通过 |
| 生产自愈 | 备份 root crontab后恢复每 2 分钟 `vps_watchdog.py` | 22:12/22:14/22:16/22:18 均由 cron 自动写入健康记录 |
| 记录同步 | v5.35.5 版本、CHANGELOG、snapshot、README、debug history、计划索引同步 | `doc_consistency.py` 7/7；根文档均未超行数上限 |
| 临时产物清理 | 空 Python 3.14 环境、无效 `uv.lock`、前序 runtime 临时结果移入 `_quarantine_20260721` | 可恢复移动；`.gitignore` 新增 `_quarantine_*/` |

## 3. 本地门禁

| 门禁 | 结果 |
|------|------|
| Python | 3.12.10，隔离 `.venv` |
| 依赖完整性 | `pip install --require-hashes` 通过；`pip check` 无冲突 |
| 全量测试 | 367 collected；360 passed；7 skipped；0 failed |
| DB Repo 注册 | 179 个委托方法，无缺失、无孤儿 |
| 文档指标 | modules=135、core=75、jobs=50、tables=167、routes=157、dispatch=9、model mappings=10；7/7 OK |
| 语法/配置 | compileall、JSON 解析、Alembic head/current、`git diff --check` 通过 |
| 凭据 | 本轮变更扫描 0 命中；`.env` 未被 Git 跟踪 |

静态质量扫描列出的 5 个 100% unused 点均已人工判读：两个是保留兼容签名的弃用参数，一个是 OpenTelemetry 接口参数，一个是 Python signal 回调固定参数，一个是无限循环后的不可达 `return`。它们不是当前运行缺陷，不为追求扫描数字而做破坏兼容性的删除。

## 4. 部署后生产证据

| 真相面 | 当前结果 |
|--------|----------|
| `mory-assistant` | active + enabled |
| `mory-dashboard` | active + enabled |
| `/api/health` | HTTP 200，`status=ok`，version=v5.35.5 |
| 版本与模块 | `VERSION=v5.35.5`；4 个修复模块 import 4/4；生产源码与本地一致 |
| 发布边界 | 仅发布 `version.py`、`scripts/puzan_loop_monitor.py`；未改 `.env`、`config.json`、数据库或依赖 |
| 备份与回滚 | 发布前备份 `/home/ubuntu/mory_assistant/backups/v5_35_5_20260721_234549`；覆盖文件部署后 SHA-256 与本地一致 |
| watchdog | root cron 恰好 1 条；23:46、23:48 连续自动记录 v5.35.5 健康 |
| 当前进程 journal | 按 MainPID 过滤后无 Traceback/ImportError/启动致命错误；旧进程退出 traceback 已定位为 gevent finalized 噪声 |
| 调度业务 | 重启后 ScheduledMessages、Wakeup、Reminders、AlertHealth 连续真实执行成功 |
| 晚间新闻 | 7 个替代真实源成功；3 个 403 源被容错；AI 超时后使用真实标题 fallback，最终 Rich Message+按钮发送成功 |
| 六层监控 | L1-L6 全部 OK，版本 v5.35.5，cron=yes，`[RECOMMEND] all normal` |

## 5. 闭环矩阵

| 项目 | 状态 | 证据 |
|------|------|------|
| Git 可信源 | PASS | `main` 已形成代码提交 `18e048e` 与预部署记录提交 `a71141c` |
| 生产版本对齐 | PASS | health 与远端导入均为 v5.35.5 |
| 服务可用性 | PASS | `mory-assistant`、`mory-dashboard` 均 active + enabled |
| 启动正确性 | PASS | 当前 MainPID 日志无结构性启动错误，4 个目标模块导入通过，DB 179/179 |
| 自愈持久性 | PASS | root cron 单实例，部署后跨两个自动周期持续健康 |
| 业务回执 | PASS | 重启后多个每分钟/每两分钟任务连续执行成功 |
| 回滚能力 | PASS | 精确备份存在，首次严格校验误判时已真实触发回滚并恢复 v5.35.4，修正证据契约后再发布成功 |

结论边界：当前已知检查面未发现未闭环故障；7 个 skipped 测试属于既有条件性跳过，24 小时长稳观察不在本次即时验收窗口内。
