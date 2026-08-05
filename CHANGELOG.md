<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# 变更日志（一行一条）

> 格式：`日期 | 类型[新增/修复/清理/文档/治理] | 一句话（≤100 字） | 涉及文件（≤5 个+等）`
> 2026-07-05 及之前的历史已归档至 `docs/archive/CHANGELOG_archive_20260707.md`；v5.38.15 及之前已归档至 `docs/archive/CHANGELOG_v5.38.15_and_before.md`。
> 触发式更新：仅用户可感知改动（升版/事故修复/配置或部署变化）写条目；验收证据写 commit message，详细报告落 `runtime/audit-reports/`。

| 日期 | 类型 | 一句话 | 涉及文件 |
|------|------|--------|----------|
| 2026-08-05 | 文档/治理 | v5.38.25 规则治理：AGENTS 触发式更新+部署三选一；doc_consistency 版本/行数/条目断言；check_deploy_ready 新增；CHANGELOG 归档压缩。 | \AGENTS.md\、\scripts/doc_consistency.py\、\scripts/check_deploy_ready.py\（新增）、\.github/workflows/ci.yml\ 等 |
| 2026-08-05 | 修复/清理 | v5.38.24 遗留闭环：mypy 10 项清零入 CI；sanitize 自愈修复生效；get_pool_info 补测试；文档治理+垃圾清理。 | \core/ai_engine.py\、\	ests/unit/test_ai_engine_resilience.py\、\project_snapshot.md\ 等 |
| 2026-08-05 | 修复 | v5.38.23 Harness 六项修复：CI 门禁断链、状态残留三路径、.venv 重建 3.12、request_id 关联。 | \core/ai_engine.py\、\core/database.py\、\.github/workflows/ci.yml\、\AGENTS.md\ 等 |
| 2026-08-05 | 修复/清理 | v5.38.22 整改收尾：CTA 收敛单一真相源；广告白名单豁免+三态降级；check_config_sync 新增；文档归档。验收：pytest 850+。 | \core/broadcast_cta.py\、\modules/ad_enforcement.py\、\scripts/check_config_sync.py\（新增）等 |
| 2026-08-05 | 修复 | v5.38.21 广告处置群管豁免：enforce_ad_user 统一处置链顶部群内管理员/群主直接豁免（覆盖 8 条调用链），修复生产误封群管实例，新增豁免单测。 | `modules/ad_enforcement.py`、`tests/unit/test_ad_enforcement.py` 等 |
| 2026-08-04 | 修复 | v5.38.20 配置脏状态闭环：MYSTIC 恢复、NEWS/AUTO_NEWS 对齐下线，合并部署验证。 | \config.json\、\AI_DEBUG_HISTORY.md\ 等 |
| 2026-08-04 | 修复/安全加固 | v5.38.20 Graph 第四轮：faq/health 明文异常改固定文案+留痕、裸 except 清场、白名单补键。验收：pytest 861。 | \dashboard/api/faq_api.py\、\dashboard/api/health_api.py\ 等 |
| 2026-08-04 | 修复/安全加固/测试 | v5.38.19 Graph 第三轮：状态日志明文脱敏 + 回退裸 except 留痕 + 4 项静态 smoke。 | \core/bot_initializer.py\、\	ests/unit/test_log_sanitization_and_trace_smoke.py\ 等 |
| 2026-08-04 | 修复/安全加固/测试 | v5.38.18 Graph 第二轮 19 处加固：metrics str(e) 修复、裸 except 留痕、白名单补键。验收：pytest 861。 | \dashboard/api/metrics_api.py\、\core/ai_engine.py\ 等 |
| 2026-08-04 | 修复/清理/安全加固 | v5.38.17：AI 超时/重试默认值与 example 三处同步对齐；wave_tilde 裸 except 留痕；deploy 补路径黑名单+EXCLUDE_NAMES 双防线。 | `core/ai_engine.py`、`deploy_vps.py` 等 |
| 2026-08-04 | 新增/优化 | v5.38.16 播报图片卡 7 项优化+20 smoke：helper 去重、CTA 强绑定、四套时段池、font LRU、deploy 上限。 | \core/broadcast_image_payload.py\、\core/broadcast_cta.py\、\deploy_vps.py\ 等 |
| 2026-08-04 | 修复 | v5.38.15.1 PIL 图片卡 Linux 汉字豆腐块根治：字体池平台分支+仓库楷体兜底；deploy 补 assets 扫描；清理 12 个孤儿临时脚本。 | `core/broadcast_image_card.py`、`deploy_vps.py` 等 |
