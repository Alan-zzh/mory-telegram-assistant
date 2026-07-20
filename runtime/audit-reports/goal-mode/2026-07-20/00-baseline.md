# 阶段 0：基线现场与回滚保护

**日期**：2026-07-20
**审计目录**：`runtime/audit-reports/goal-mode/2026-07-20/`

---

## 1. Git 状态

| 项 | 值 |
|---|---|
| HEAD | `77e849a17ff64509193bd52e28b5a461c4e5bb4a` |
| 分支 | `main` |
| 远程 | `origin  https://github.com/Alan-zzh/mory-telegram-assistant.git` |
| 与 origin 关系 | `main...origin/main [ahead 3]`（本地领先 3 提交未推送） |
| Modified | 41 文件 |
| Untracked | 41 modules + 4 audit-reports + browser-scan/ |
| Deleted | `uv.lock`（已删） |

## 2. .gitignore 检查

✅ 已包含：`.env` / `.env.*` / `!.env.example` / `config.json` / `*.db` / `*.db-journal` / `*.db-wal` / `logs/` / `backups/` / `__pycache__/` / `.venv/` / `*.log` / `*.bak` / `fault_dedup_state.json` / `data/`

✅ 敏感脚本过滤：`force_*.py` / `verify_*.py` / `check_*.py` / `fix_*.py` / `diagnostic*.py` / `scan*.py` / `deploy_*.py`（白名单 `deploy_vps.py`）/ `full_sync*.py`

✅ 根目录临时文件过滤：`_*.py` / `_*_*.py` / `tmp_*.txt` / `test_out.txt` / `test*.txt`

## 3. 文档一致性（doc_consistency.py）

```
指标                                    实际      声明  结果
------------------------------------------------------------
modules 业务 .py（不含 __init__）        135     135  OK
core 业务 .py（不含 __init__）            75      75  OK
auto_tasks.py 中 _job_ 函数            50      50  OK
database.py CREATE TABLE 数         167     167  OK
dashboard/api 路由装饰器数               157     157  OK
消息分发函数（含导入的 p10）                     9       9  OK
model_router 任务类型映射数                10      10  OK
```

✅ 7/7 全过

## 4. 数据库方法注册（verify_db_methods.py）

```
✅ DB 方法注册验证通过：179 个委托方法，无缺失、无孤儿
```

## 5. Python 环境

- Python 3.12.9（Windows）
- pytest 9.0.3
- prometheus-client 0.25.0（本会话已安装）

## 6. 当前指标基线

| 指标 | 值 |
|---|---|
| modules 业务 .py | 135 |
| core 业务 .py | 75 |
| _job_ 函数 | 50 |
| DB 表 | 167 |
| Dashboard 路由 | 157 |
| 消息分发函数 | 9 |
| model_router 映射 | 10 |
| Repo 方法 | 179 |
| VERSION | v5.35.2 |
| CONFIG_VERSION | 5.35.2 |

## 7. 已知失败/风险

- 本地仓库 v5.35.2 比 origin/main 领先 3 提交 + 41 modified + 41 untracked modules（v5.34.0/v5.35.0 新增模块）+ 4 untracked audit-reports 未提交
- runtime/audit-reports/ 下有 4 个未提交的旧审计报告（GOAL_FULL_IMPLEMENTATION_ACCEPTANCE_20260718.md / MORY_PROJECT_AUDIT_FOR_CLAUDE.md / _expert_A_architecture_static.md / _expert_B_database_persistence.md）
- runtime/browser-scan/ 未提交
- `uv.lock` 已删除（与 requirements.lock 二选一）

## 8. 不确定信息

- runtime/browser-scan/ 来源不明，可能是之前会话留下的扫描结果
- 4 个旧审计报告是否需要保留待定（按 AGENTS.md 文档路由表，审计报告归 `runtime/audit-reports/`，但 7/18 的报告已过时）

## 9. 回滚策略

- 当前 HEAD `77e849a` 作为回滚锚点
- 41 modified + 41 untracked 全部是 v5.35.2 同步内容，已通过 doc_consistency + verify_db_methods + pytest 274/274 验证
- 如需回滚：`git reset --hard 77e849a` + 删除 41 个 untracked modules
- VPS 已是 v5.35.2 运行正常（双服务 active+enabled, health 200, journal 1h 无 ERROR）

## 10. 下一阶段建议

进入阶段 1：全面体检。用多智能体并行检查 11 个分区（A-K），输出问题清单到 `10-issues.md`。
