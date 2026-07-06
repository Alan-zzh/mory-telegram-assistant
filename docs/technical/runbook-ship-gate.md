# Runbook: 改动后验证 + 收工六件套（ship-gate）

> 用途：任何部署或代码改动"宣告完成"前，必须过本门禁。证据不足不得宣称完成。
> 桥接 Puzan OS `deploy-automation`（Pre-deploy Git Hygiene Gate）与本项目专属验证。

## 门禁（任一失败 → 停止、报告、不宣称完成）

### Gate 1 — Git 卫生（来自 Puzan OS deploy-automation）
```bash
git status --porcelain
```
- 输出非空 → **先本地 commit 再继续**；绝不在脏工作树部署 / 宣称完成。
- 本项目教训（2026-07-07）：media 清理删 2 个 service + 改 `deploy_vps.py` 后未提交，下次部署会重传坏桩。

### Gate 2 — 双核心服务 + 健康
```bash
systemctl status mory-assistant mory-dashboard --no-pager   # 均 active
curl -s -o /dev/null -w '%{http_code}\n' localhost:6616/api/health   # 200
```

### Gate 3 — DB 方法注册
```bash
python scripts/verify_db_methods.py   # 输出 "✅ DB 方法注册验证通过"
```
新增 / 删除 Repo 方法须同步 `core/database.py` 的 `_REPO_METHOD_MAP` / `_REPO_ATTR_MAP`。

### Gate 4 — 文档数字一致性
```bash
python scripts/doc_consistency.py   # 退出码 0
```

## 收工六件套（根文档仅限六文档，须保持同步）
改动后按影响更新对应文档（禁止"下次再补"）：
1. `CHANGELOG.md` 追加：`日期 | 类型 | 一句话 | 涉及文件`。
2. `project_snapshot.md` 覆盖更新对应模块状态区块（METRICS 与代码一致）。
3. `AI_DEBUG_HISTORY.md` 有新教训则按（问题 | 根因 | 解法 | 预防）追加。
4. `VERSION.md` 版本 / 阶段有变则 bump。
5. `AGENTS.md` 规则 / 约定有变则同步。
6. `README.md` 入口 / 快速开始有变则同步。
完成后重跑 `python scripts/doc_consistency.py`。

## 证据要求
至少两条：修改文件 + diff 摘要 / 命令输出 / 测试结果。
