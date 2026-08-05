# Runbook: 删除 / 重构前引用清扫（safe-change）

> 用途：删除文件、下线服务、重构前，先确认无悬空引用、无破坏部署 / 双核心。

## 步骤
1. **全仓搜引用**：`search_content` 目标名（如 `mory-media`、服务名、符号、DB 名）。
   - 有引用 → 先处理引用再删，或确认引用点已废弃。
2. **确认部署守卫**：若删的是 `config/*.service` 或部署引用，确认 `deploy_vps.py` 有 `if local_svc.exists()` 类守卫，删文件不会让后续部署报错或重建坏桩。
3. **DB 方法**：删 Repo 方法须同步移除 `_REPO_METHOD_MAP` / `_REPO_ATTR_MAP` 映射，重跑 `verify_db_methods.py`。
4. **配置安全**：
   - 禁止 `sftp.put('config.json')` 覆盖 VPS（用 `safe_upload_config()`）。
   - 禁止上传 `mory.db`。
5. **不动双核心**：不碰 `mory-assistant` / `mory-dashboard` 单元与 `main.py` 入口。
6. **指标同步**：删模块 / 表 / 路由 / 任务后，更新 `project_snapshot.md` 的 METRICS 块并跑 `doc_consistency.py`。
