# 8 大类老坑 · 运维铁律（部署/迁移/AI 自我审计）

> 本文档为独立技术说明，未被 AGENTS.md 直接索引 · 适用版本：v5.12.1+
> **最后更新**：2026-06-02（v5.12.1 新建，与 anti-patterns-code.md 配合）

## 概述

本文件是 `AGENTS.md` 中"⚠️ 8 大类老坑铁律"的**运维层面** 4 大类（3, 5, 7, 8）：
- **核心代码 5 大类**（沉默失败/配置/DB 注册/关键路径/VPS 部署）见 [anti-patterns-code.md](anti-patterns-code.md)
- **运维 4 大类**（部署一致性/half-migrated/AI 自我审计/VPS 部署）见本文件
- 详细翻车案例 → `AI_DEBUG_HISTORY.md`

---

## 类别 3：部署一致性 6 条铁律

> 关键：**VPS 文件 owner / 服务文件 / 部署顺序 / 端口冲突 / 凭据注入 / 强制重启**

| # | 铁律 | 关键命令 |
|---|------|---------|
| 3.1 | **VPS 文件 owner** 部署后 `sudo chown -R ubuntu:ubuntu {VPS_PATH}/{core,modules,dashboard}` | `sudo chown -R ubuntu:ubuntu /home/ubuntu/mory_assistant/{core,modules,dashboard}` |
| 3.2 | **服务文件必带 EnvironmentFile** `.env` 凭据不在 systemd unit 内 | `grep -A1 "EnvironmentFile=" mory-assistant.service` |
| 3.3 | **部署顺序** stop → 上传 → start → 验证，**禁止热替换** | `systemctl stop mory-assistant && deploy && systemctl start` |
| 3.4 | **端口冲突** Dashboard 6616 固定，Bot 不同实例错开 | `ss -tlnp \| grep -E "6616\|main.py"` |
| 3.5 | **凭据注入** `EnvironmentFile=/home/ubuntu/mory_assistant/.env` | `cat /home/ubuntu/mory_assistant/.env \| grep -c KEY` |
| 3.6 | **强制重启验证** 部署后 `restart + tail log` 必跑 | `systemctl restart mory-assistant && sleep 3 && journalctl -u mory-assistant -n 20` |

**翻车记录**：v5.11.0 root 用户上传文件 → ubuntu 权限不足 → 服务起不来。
**详情**：[docs/technical/vps-deploy-trap.md](vps-deploy-trap.md)

---

## 类别 5：half-migrated 状态 3 条铁律

> 关键：**改 schema.py 必须同步执行 migration / 老代码半迁移状态禁止上线 / 验证表结构**

| # | 铁律 | 关键命令 |
|---|------|---------|
| 5.1 | **改 schema.py 必须同步迁移** 单独建表不算迁移成功 | `python -c "import sqlite3; c=sqlite3.connect('mory.db'); print([r[0] for r in c.execute('SELECT name FROM sqlite_master WHERE type=\"table\"')])"` |
| 5.2 | **ALTER TABLE 可能假成功** 迁移日志"OK"但表结构未变 | `python -c "import sqlite3; c=sqlite3.connect('mory.db'); print(c.execute('PRAGMA table_info(broadcast_tracking)').fetchall())"` |
| 5.3 | **旧模式必须清零** `_can_run` / `_mark_done` / `_release_task` 拆分后**老逻辑删除** | `grep -rn "_can_run\|_mark_done\|_release_task" core/ modules/ --include="*.py"` |

**翻车记录**：v5.9.1 `_can_run` 拆分半迁移，老逻辑仍被调用导致死锁。
**详情**：`AI_DEBUG_HISTORY.md` v5.9.1 节

---

## 类别 7：AI 自我审计 4 条铁律

> 关键：**改前必查 3 文档 / 不重复造轮子 / 不凭空报行号 / 失败升级机制**

| # | 铁律 | 关键命令 |
|---|------|---------|
| 7.1 | **改前必查 3 文档** 任何 bug/需求先读 `AGENTS.md` / `AI_DEBUG_HISTORY.md` / `CHANGELOG.md` | `ls AGENTS.md AI_DEBUG_HISTORY.md CHANGELOG.md` |
| 7.2 | **不重复造轮子** grep 现有实现优先复用，不写新逻辑 | `grep -rn "def track_bot_message" core/ modules/ --include="*.py"` |
| 7.3 | **不凭空报行号** 引代码前先 `grep -n` 确认位置 | `grep -n "create_broadcast_tracking" core/database.py` |
| 7.4 | **失败升级机制** 1次重试 → 2次换参数 → 3次换方案 → 仍失败告知用户 | （行为纪律） |

**翻车记录**：v5.11.0 没查 3 文档就写新方法 `track_bot_message` 但漏注册到 `_REPO_METHOD_MAP` → 静默失败。
**详情**：`AI_DEBUG_HISTORY.md` v5.11.0 节 坑1

---

## 类别 8：VPS 部署 5 条铁律（运维速查）

> 详细代码块与验证命令见 [anti-patterns-code.md](anti-patterns-code.md) 类别 8
> **运维速查**：

| # | 铁律 | 关键命令 |
|---|------|---------|
| 8.1 | **chown 检查** 每次部署前自动 | `find /home/ubuntu/mory_assistant/{core,modules,dashboard} ! -user ubuntu` |
| 8.2 | **服务文件 owner** | `ls -la /etc/systemd/system/mory-*.service` |
| 8.3 | **依赖完整性** 部署后 `pip install -r requirements.txt` | `pip check` |
| 8.4 | **deploy_vps.py 必跑** | `python deploy_vps.py --check` |
| 8.5 | **mory.db 不覆盖** VPS 数据库与本地不同步 | `ls -la /home/ubuntu/mory_assistant/mory.db` |

---

## 引用

- [AGENTS.md](../../AGENTS.md) — 精简铁律 + 引用本文件
- [anti-patterns-code.md](anti-patterns-code.md) — 核心代码 5 大类（沉默失败/配置/DB 注册/关键路径/VPS 部署）
- [vps-deploy-trap.md](vps-deploy-trap.md) — VPS 部署陷阱（部署一致性 6 条铁律完整版）
- [orphan-cleanup.md](orphan-cleanup.md) — 孤儿清理机制
- [config-reload.md](config-reload.md) — 配置热重载
- [ad-detection.md](ad-detection.md) — 广告检测
- [../../AI_DEBUG_HISTORY.md](../../AI_DEBUG_HISTORY.md) — 病历本（翻车案例）

## 更新历史

- 2026-06-02 (v5.12.1) — 新建（从 anti-patterns.md 拆出运维 4 大类 3, 5, 7, 8）
