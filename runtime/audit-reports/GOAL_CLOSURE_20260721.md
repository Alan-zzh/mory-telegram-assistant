# v5.35.5 整仓修复与生产闭环报告

> 日期：2026-07-21
> 当前判定：`PREDEPLOY_VERIFIED`
> 最终完成条件：形成可信 Git commit，并将该 commit 的最小运行文件发布到生产后复验。

## 1. 结论

本轮不是复述旧报告，而是重新以当前工作树、隔离环境和 VPS 为真相面执行验收。已确认并修复三类真实漂移：

1. Git `main` 中 4 个已修模块被一次 VPS→本地反向同步覆盖回断链实现；生产文件反而保持正确。
2. 生产外部 watchdog cron 消失约 12 天，但旧 loop-monitor 仍输出 `all normal`。
3. 本地 `.venv` 是无 pip/依赖的 Python 3.14 空环境，未跟踪 `uv.lock` 也没有项目依赖；README 口径失真。

截至本报告写入时，本地 v5.35.5 已通过全部门禁，生产 v5.35.4 服务与业务正常且 watchdog 已恢复持续运行。尚未宣称最终闭环，因为 Git 默认分支提交选择仍待老板确认，生产版本也尚未从 v5.35.4 升到 v5.35.5。

## 2. 修复范围

| 范围 | 修复内容 | 证据 |
|------|----------|------|
| 模块回归 | 恢复 `anti_raid`、`group_members`、`punishment_center`、`crypto_detector` 正确实现 | 50 个历史回归测试全过；与生产文件逐字对比一致 |
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

## 4. 当前生产证据

| 真相面 | 当前结果 |
|--------|----------|
| `mory-assistant` | active + enabled |
| `mory-dashboard` | active + enabled |
| `/api/health` | `status=ok`，version=v5.35.4 |
| 四个修复模块 | 生产 import 全部 OK；文件与本地修复后逐字一致 |
| watchdog | root cron 仅 1 条；每 2 分钟持续健康执行 |
| 近期 journal | watchdog 恢复后无未解释 Traceback/Exception/Error/Timeout/OOM |
| 调度业务 | morning/afternoon/evening 播报、问候、日报等 task key 均有当日记录 |
| 晚间新闻 | 7 个替代真实源成功；3 个 403 源被容错；AI 超时后使用真实标题 fallback，最终 Rich Message+按钮发送成功 |

## 5. 当前未闭环项

| 项目 | 状态 | 原因 |
|------|------|------|
| Git 可信源 | PENDING | 当前仍在默认分支 `main` 且工作树未提交；提交技能要求老板确认直接 main 或新分支 |
| 生产版本对齐 | PENDING | 本地 v5.35.5，生产 v5.35.4；修复后的 monitor 已正确报告 NEEDS_REVIEW |
| 部署后持久复核 | PENDING | 必须从可信 commit 发布后，再复查双服务、health、journal、watchdog、版本与业务任务 |

在上述三项完成前，不得把本报告状态改为 `VERIFIED_CLOSED`，也不得宣称“全部无问题”。
