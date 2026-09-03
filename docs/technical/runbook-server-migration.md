# Runbook: 换服务器迁移（server-migration）

> 目标：换新 VPS 时零丢失、一键恢复。代码以 git 为准，数据以现生产服快照为准。
> 工具：`scripts/migrate_export.py`（导出）+ `scripts/migrate_restore.py`（恢复）。
> 红线：恢复脚本只写**全新空目标**（已存在 `mory.db` 直接拒绝）；老服务器在切换验证前不动。

## 数据清单（以 2026-09-03 实测为准）

| 项 | 位置（现生产服） | 是否 git 在库 | 迁移方式 |
|---|---|---|---|
| `mory.db`（186 表/约48400 行，WAL 含最新写入） | `/home/ubuntu/mory_assistant/mory.db*` | 否（.gitignore） | 在线一致性快照（sqlite backup API），不断服 |
| `config.json`（生产运行配置真相，256 键） | 同上 | 否 | 快照原样带走 |
| `.env`（凭据/VPS 连接/Dashboard 密钥） | 同上 | 否 | 快照原样带走 |
| `data/router_usage.db`（用量/费用 guard） | 同上 | 否 | 一致性快照 |
| `assets/fonts/*.ttf`（图片卡中文字体，19MB） | 同上 | 否 | 原样带走 |
| `assets/broadcast/*`（播报底图） | 同上 | 否 | 原样带走 |
| `fault_dedup_state.json` | 同上 | 否 | 原样带走 |
| 历史归档（近3份 hourly DB + 全部 pre-migration DB + 配置备份） | `backup/` + `backups/` | 否 | `--with-history` 打包（更老的 hourly 留老服，见下） |
| 其余 `backups/` 代码 tarball、`runtime/cache`、`logs/`、`mory.log` | 同上 | 否 | **不迁**（代码 tarball 可由 git 重建；缓存/日志为运行态） |
| 代码 | git `main` @ commit | 是 | 新服 `git clone + checkout <commit>` |
| `/opt/moryfansbot`（独立媒体 Bot，读 `promotions` 表） | **不在本仓库** | — | 新服需单独迁移，本 runbook 只做登记提醒 |

说明：28 份更老的 hourly DB 备份保留在老服务器原位（导出报告 `skipped_old_hourlies` 列清单），
老服在切流验证通过前保留不断电，需要时可随时补拉。代码 tarball 不迁出是因为 git commit 可精确重建。

## 操作步骤

```bash
# 0. 本地确认版本一致（现生产服 version.py == 本地 version.py）
# 1. 导出（活数据约 40MB；--with-history 约 52MB）
python scripts/migrate_export.py --with-history
#    产物 backups/server_migrate_<UTC戳>/：live-data.tar.gz + history-data.tar.gz
#    + live/ + MANIFEST.json + VERIFY_REPORT.json（10 项须全绿）
#    断点续传：同命令加 --out-dir <中断目录> --resume-stage <远端staging名>

# 2. 新服务器就绪后：先预检（只读）
set NEW_VPS_HOST=<新IP> & set NEW_VPS_SSH_PASS=<密码或密钥>
python scripts/migrate_restore.py --export-dir backups/server_migrate_<戳> --check-only

# 3. 一键恢复（约10分钟：clone→还数据→pip lock→alembic head→units→restart→health+版本+完整性读回）
python scripts/migrate_restore.py --export-dir backups/server_migrate_<戳>

# 4. 切流后验证（按 runbook-ship-gate 部署判据）：双服务 active、health=200、
#    版本读回、DB integrity、受影响业务探针；老服保留至少一个备份周期再下线。
```

## 失败处理

- 导出校验任一项变红 → 该包不可作恢复源，按 `VERIFY_REPORT.json` 重跑。
- 恢复脚本任一步失败 → 直接报错退出，**不**自动重试重启；老服未动，新服可清空重跑。
- 恢复后 health 不过 → 看新服 `journalctl -u mory-assistant -n 100 --no-pager`，与本次无关的旧问题先记 `evidence_gap`。
