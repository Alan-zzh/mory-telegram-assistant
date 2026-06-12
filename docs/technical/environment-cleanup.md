# 环境清理记录

> 最后更新：2026-06-12 [Codex]

## 2026-06-12 本地清理

### 清理原则

- [Codex] 只清缓存、旧日志、明确临时脚本，不删除源码、配置、数据库、凭据、systemd 相关文件。
- [Codex] 清理前已备份计划相关文件到 `backup/codex_20260612_230136_ad_governance/`。
- [Codex] 本地 Git 工作区原本已有大量非本次变更，清理和提交只处理本次计划相关文件。

### 已删除

- [Codex] Python 缓存：`__pycache__`、`core/**/__pycache__`、`dashboard/**/__pycache__`、`modules/__pycache__`、`scripts/__pycache__`、`tests/unit/__pycache__`
- [Codex] Pytest 缓存：`.pytest_cache`
- [Codex] 根目录旧日志：`mory.log`、`scan.log`
- [Codex] 临时脚本：`scripts/_monitor_v5161.py`、`scripts/_verify_deploy_v5161.py`

### 保留

- [Codex] 保留 `.env`、`config.json`、`mory.db`、`backup/`、`logs/`、部署脚本、SSH helper、成员扫描、广告验证、孤儿清理、VPS 清理类脚本。

## VPS 清理

- [Codex] 已执行。原则：只清 `/home/ubuntu/mory_assistant/` 下缓存、旧临时脚本、过期日志和无用备份；不触碰 `.env`、`config.json`、`mory.db`、systemd 配置。

### 已删除

- [Codex] Python 缓存：`__pycache__`（根目录、`core/`、`core/db_repos/`、`core/handlers/`、`dashboard/`、`dashboard/api/`、`dashboard/templates/`、`modules/`）
- [Codex] 根目录旧日志：`mory.log`
- [Codex] 旧临时脚本：`scripts/_task1_4_retry5.py`、`scripts/_task1_4_retry4.py`、`scripts/_diag_vps.py`、`scripts/_task1_vps_acceptance.py`、`scripts/_task3_history_msg.py`、`scripts/_task1_4_retry2.py`、`scripts/_task2_e2e2.py`、`scripts/_task1_4_retry3.py`、`scripts/_task2_e2e.py`、`scripts/_debug_ssh.py`、`scripts/_task3_history_msg2.py`、`scripts/_task1_4_retry.py`

### 保护验证

- [Codex] 远端 `.env`、`config.json`、`mory.db` 均存在。
- [Codex] `mory-assistant`、`mory-dashboard` 均为 active。
- [Codex] `http://localhost:6616/api/health` 返回 200。
- [Codex] 部署后最近 5 分钟 journal 未发现 Traceback / ImportError / ERROR / Exception。
