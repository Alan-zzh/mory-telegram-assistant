# core/db_repos 模块规则

## 职责边界
- 本目录是唯一的数据仓储层：每个 Repo 封装一个业务域的数据访问，禁止在 Repo 外直接拼接 SQL。
- 新建 Repo 文件或新增 public 方法时，必须同步注册 `core/database.py` 的 `_REPO_METHOD_MAP` 与 `_REPO_ATTR_MAP`，否则启动直接失败。

## 验收锚点
- 部署前必跑：`python scripts/verify_db_methods.py`，输出"✅ DB 方法注册验证通过"才可上线。
- 涉及表结构变更：同步 Alembic migration，部署后验证表结构。
- 新增 SQL 一律 `CREATE TABLE IF NOT EXISTS`。
