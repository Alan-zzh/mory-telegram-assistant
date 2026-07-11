<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# Mory小助理 项目状态快照（覆盖式）

> 本文件每次整段覆盖对应区块，禁止无限追加。最后更新：2026-07-10。

## 一句话
Telegram 群组助手机器人 Mory小助理：人设对话、广告检测、群管、积分商城、转化漏斗、新闻播报、运营 Dashboard。单机 VPS 部署（systemd 唯一）。

## 模块状态表
| 模块 | 状态 | 入口文件 | 备注 |
|------|------|----------|------|
| 消息总分发 | 在用 | `core/message_dispatcher.py` | 9 个分发函数（8 定义 + 导入 `_dispatch_p10_ai`） |
| AI 回复 / 人设 | 在用 | `core/handlers/ai_reply_handler.py`、`core/ai_engine.py`、`core/persona_adapter.py` | `SYSTEM_PROMPT` 从 config 读取 |
| 模型路由 | 在用 | `core/model_router.py` | 7 个截图指定文本型号按到期日升序；`qwen3.5-ocr` 归视觉池 |
| 定时任务 | 在用 | `modules/auto_tasks.py` | 53 个 `_job_` 函数 |
| 广告检测 | 在用 | `modules/ad_detector.py`、`core/handlers/security_handlers.py` | L0–L4 五层 |
| 群管 / 积分 / 娱乐 | 在用 | `modules/*.py` | 92 个业务 `.py` |
| 孤儿清理 | 在用 | `orphan_api.py`、`burn_orphan_task.py` | 端到端串联 |
| 入群验证 | 在用 | `modules/verification.py` | button / puzzle / timeout / max_attempts |
| Dashboard | 在用 | `dashboard/app.py`、`dashboard/api/*.py` | 157 个路由，端口 6616 |
| 数据库 | 在用 | `core/database.py`、`core/db_repos/*.py` | 108 张表 |
| 配置 | 在用 | `core/settings.py` + `config.json` | 密钥仅 `.env` |
| 转化漏斗 | 在用 | `social_repo.py` + `message_dispatcher` | `conversion_events` 各阶段 |
| 记忆 / 画像 | 在用 | `memory_summarizer.py`、`profile_learner.py` | `profile_learner` 的 `sticker` 维度未入库 |

## 当前版本
v5.31.6（2026-07-10）

## 最近 3 条大事
1. 2026-07-10 AI 模型池按最新额度清单重置：7 个文本型号进入主池与三层池并按到期日升序优先，`qwen3.5-ocr` 进入视觉池；旧型号、示例黑名单与 A/B 覆盖已清除。
2. 2026-07-10 部署脚本健壮性修复：pip 快速预检跳过 + SIGTERM 信号兜底 + 健康轮询确认 + finally 独立重连重启；删除 `nil` 等本地脏文件。
3. 2026-07-10 广告检测补漏：`发~财` 模糊匹配 + `加我wx/加我v/加我微信` 联系方式模式，修复 `发财` 不匹配 `发大财了` 的问题。

## 客观指标（供 `scripts/doc_consistency.py` 断言，勿手改）
<!-- METRICS:BEGIN -->
modules_py=91
core_py=74
job_count=53
db_tables=108
dashboard_routes=157
dispatch_funcs=9
model_router_mappings=10
<!-- METRICS:END -->
