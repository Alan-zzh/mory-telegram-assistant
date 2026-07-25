<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# Mory小助理

Telegram 群组助手机器人：人设对话、广告检测、群管、积分商城、转化漏斗、新闻播报、运营 Dashboard。单机 VPS（systemd）部署。

当前版本 **v5.35.16**：MoryFansBot 与 Mory小助理共用同一套对话原则——先接住当前话题，普通聊天不按固定轮数硬推；价格、内容和权益先去预览，明确购买、看过预览或明确提出定制需求后才进入自助订阅。拒绝、取消和定制概念咨询不推进，近期已给过下单入口时只继续承接细节；私聊零按钮，群聊每轮只有一个与正文一致的入口。

## 快速开始

### 环境
- Python 3.12+；唯一依赖锁为 `requirements.lock`；虚拟环境 `.venv/`。
- 敏感凭据仅在 `.env`（`TG_TOKEN` / `DASHSCOPE_KEY` / `DASHBOARD_SECRET` / `DASHBOARD_PASSWORD` 等），绝不入库。

### 本地运行
```bash
pip install -r requirements.lock
cp .env.example .env   # 填入真实凭据
python main.py
```

### 部署（仅 VPS，systemd 唯一）
```bash
sudo systemctl restart mory-assistant     # 主进程
sudo systemctl restart mory-dashboard     # Dashboard，端口 6616
python deploy_vps.py                       # stop→上传→start→验证（safe_upload_config 保护密钥）
```
部署后验证：`systemctl status` 双 active + `curl localhost:6616/api/health`。
项目默认把生产部署纳入更新/修复闭环：本地门禁通过并提交可信 Git commit 后直接增量部署；仅限本地、无运行态影响或安全门禁阻断时跳过。完整约束以 `AGENTS.md` 为准。

## 目录结构
- `core/`：消息分发、AI 引擎、模型路由、数据库、配置、handler。
- `modules/`：135 个业务模块（广告检测、群管、积分、转化、播报、定时任务、销售/安全/多群托管/会员等 v5.34.0+ 默认关闭）。
- `dashboard/`：运营后台（`app` + `api`，157 路由）。
- `tasks/`：后台定时任务（`task_scheduler.py` 自动发现 BaseTask 子类；`auto_tasks.py` 为 legacy）。
- `scripts/`：工具脚本（含 `doc_consistency.py` 自检）。
- `tests/`：单元测试。
- `docs/`：技术(`technical`)、计划(`plans`)、愿景(`vision`)、归档(`archive`)。
- `migrations/`：Alembic 数据库迁移。
- `runtime/audit-reports/`：审计报告与完工报告。
- `config/`：systemd 服务文件。

## 客观指标（2026-07-19 实测，`scripts/doc_consistency.py` 全过）
modules 业务 `.py` = 135，core 业务 `.py` = 75，`_job_` = 50，DB 表 = 167，Dashboard 路由 = 157，消息分发函数 = 9，model_router 映射 = 10。
一致性由 `scripts/doc_consistency.py` 断言（`project_snapshot.md` 的 `METRICS` 块为基准）。

## 六大文档索引
- `AGENTS.md`：项目规则唯一入口（铁律 / 流程 / 约定 / 文档路由表）。
- `README.md`：本文件。
- `VERSION.md`：当前版本号与升版规则。
- `CHANGELOG.md`：用户可感知变更（一行一条）。
- `project_snapshot.md`：当前真实状态快照（覆盖式）。
- `AI_DEBUG_HISTORY.md`：反复暗病病历（问题 | 根因 | 解法 | 预防）。

## 常见问题
- **文档数字以哪为准？** 以 `project_snapshot.md` 的 `METRICS` 块 + `scripts/doc_consistency.py` 校验为准；README 中的数字与其一致。
- **改了配置为何不生效？** 配置三处同步：`config.json.example` + 代码 `.get()` 默认值 + Dashboard 面板；改后需重启对应 systemd 服务。
- **新增数据库表 / Repo 方法？** 必须同步 Alembic migration 与 `core/database.py` 的 `_REPO_METHOD_MAP` / `_REPO_ATTR_MAP` 注册，否则启动失败；部署前跑 `python scripts/verify_db_methods.py`。
- **密钥泄露怎么办？** 立即在 `.env` 与对应平台更换，旧密钥视为失效；本项目密钥均已 gitignore，勿提交。
