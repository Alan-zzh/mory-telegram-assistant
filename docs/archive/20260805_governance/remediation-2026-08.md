# 2026-08 整改收尾计划（v5.38.22）

> 落点：`docs/plans/`（文档路由表规定的"计划/方案"目录）
> 创建：2026-08-05 | 状态：已执行完成（v5.38.22）
> 依据：`.trae/documents/broadcast_visual_upgrade_plan.md`（2026-08-03 播报视觉升级计划，Phase 3 收口）+ `docs/plans/remediation_roadmap.md`（2026-07-07 已完成）

## 背景

播报视觉升级计划（v5.38.15/16 图片卡）落地后仍存在"表面做完、实际不一致"的遗留问题：CTA 三套真相源并存、广告处置豁免链有误封风险、Graph Mode 扫描有残余、文档超限。本轮四项整改 + 两段式发布闭环。

## 整改范围

| 领域 | 内容 |
|------|------|
| 播报/图片卡收尾 | 删除 `broadcast_image_card.py` 旧 CTA 池与 `get_random_cta`、删除 `cta_pool` 死参数（6 调用点）、收敛 `mystic_content.py` 第二套 CTA 系统（`_CTA_URLS/_CTA_LABEL_POOLS/_CTA_CLOSING_POOLS/_build_cta`）为统一 `core/broadcast_cta.py` 单一真相源、四路图片卡开关收敛 `is_broadcast_image_enabled`、视觉常量对齐计划（CTA 圆角 18/标签 8）、缓存存在性短路 + 原子写、`_stable_seed` 改 md5 确定性、拼音检测中文过滤 |
| 广告检测与群管治理 | `enforce_ad_user` 配置级 `_admin_ids` 白名单豁免前置（零网络）、`_is_chat_admin_member` 三态降级（unknown 跳过不可逆惩罚 + 通知人工复核）、启动追溯跳过计数不误报"禁言失败"、入群检测路径 `_is_member_ad_exempt` 豁免拉齐 |
| 代码质量与安全 | `config_api.py` 裸 except 留痕、新增 `scripts/check_config_sync.py` 三处同步差集断言 + 白名单补 10 个业务键、PII 泄露复查 0 命中 |
| 文档与项目治理 | `AI_DEBUG_HISTORY.md` 归档（362→93 行）、`CHANGELOG.md` 近期超长条目压缩（97.6KB→89.7KB）、新增病历 54/55 两条 |

## 执行结果

- 本地验证：全仓 pytest 850+ passed 基线、`doc_consistency.py` 7/7、`verify_db_methods.py` 199/199、`check_config_sync.py` 退出 0、demo 六张样张生成。
- 两段式发布：commit 1（v5.38.21 工作区）→ 部署 → 生产验收通过；commit 2（v5.38.22 整改）→ 部署 → 生产验收通过。
- 版本：v5.38.21 → v5.38.22。

## 验证方式

- 每个阶段验证：py_compile + 相关单测 + 静态断言（grep 旧符号零残留）。
- 部署后：双服务 active + health 200 + 版本 + journal 无 Traceback + mystic 三任务注册 + 真实播报回执。

## 关联

- `.trae/documents/broadcast_visual_upgrade_plan.md`：Phase 1/2（v5.38.15/16）与 Phase 3（CTA 统一/视觉收口/验证）已全部落地，本轮即 Phase 3 收口。
- `docs/plans/remediation_roadmap.md`：2026-07-07 整改已完结，本轮为后续整改批次。
