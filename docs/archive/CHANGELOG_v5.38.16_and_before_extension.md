<!-- 文档守则：本文件为归档副本，不再维护；新变更一律写入根 CHANGELOG.md。 -->

# CHANGELOG 补充归档（v5.38.15.1 ~ v5.38.16）

> 归档日期：2026-08-24。根 CHANGELOG 新增生产热修记录后触发 80 行熔断。

| 日期 | 类型 | 一句话 | 涉及文件 |
|------|------|--------|----------|
| 2026-08-04 | 新增/优化 | v5.38.16 播报图片卡 7 项优化+20 smoke：helper 去重、CTA 强绑定、四套时段池、font LRU、deploy 上限。 | `core/broadcast_image_payload.py`、`core/broadcast_cta.py`、`deploy_vps.py` 等 |
| 2026-08-04 | 修复 | v5.38.15.1 PIL 图片卡 Linux 汉字豆腐块根治：字体池平台分支+仓库楷体兜底；deploy 补 assets 扫描；清理 12 个孤儿临时脚本。 | `core/broadcast_image_card.py`、`deploy_vps.py` 等 |
