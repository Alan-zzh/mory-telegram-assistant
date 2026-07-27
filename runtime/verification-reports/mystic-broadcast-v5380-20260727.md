# Verification 报告

- **task_id**：mystic-broadcast-v5380-20260727
- **执行时间**：2026-07-27
- **truth_surface**：本地 Windows checkout；生产 VPS `/home/ubuntu/mory_assistant`；生产 Telegram 管理员 Rich Message。
- **目标**：把僵硬的四行玄学卡重做为三个专业、差异化、适合群聊的传统文化栏目，并以单目标按钮自然承接互动和转化。

## 产品与来源

- 早间 `早间 · 今日黄历`：生产使用 `cnlunar==0.2.4`，展示真实农历、干支、宜忌、冲煞、值日、星宿、吉神方位、节气和彭祖百忌。
- 午间 `午间 · 三张塔罗`：22 张大阿卡纳中无重复抽取主牌、助力、提醒，分别含正逆位、元素、关键词和组合观察。
- 晚间 `晚间 · 易经一卦`：完整文王六十四卦映射，展示本卦、上下卦、一个动爻、由爻位翻转得到的之卦及变化观察。
- 三档产品身份固定；日期、时段和栏目参与稳定 seed，同日重试一致、跨日变化。
- 开源比较与许可证判断见 `docs/research/mystic-broadcast-open-source-20260727.md`。

## 本地门禁

- 整仓测试：`492 passed, 7 skipped`。
- DB 委托：`190/190`，无缺失、无孤儿。
- 文档指标：`7/7` 一致。
- 相关 Python 编译、`git diff --check`、`pip check` 和 `requirements.lock --require-hashes` dry-run 通过。
- 关键回归覆盖：真实黄历字段、三张不同牌、64 个唯一卦象线型、单爻变卦、同日幂等、三目标轮换、单按钮、Rich/HTML 双排版和发送追踪。

## 部署证据

- 可信提交：`bcd095e6d297bf8d62db962ad65539f4a4914ee2`。
- 生产备份：`/home/ubuntu/mory_assistant/backups/deploy_v5380_20260727_153015`。
- 23 个发布文件先上传 staging 并逐个校验 SHA-256，再在部署锁内备份、停止双服务、原子替换和重启；11 个关键运行文件发布后与本地哈希 `11/11` 一致。
- `mory-assistant`、`mory-dashboard` 重启后均 active+enabled，NRestarts=0，health 返回 `{"status":"ok","version":"v5.38.0"}`，当前进程 error journal 为空。
- 生产包元数据确认 `cnlunar=0.2.4`；生产 DB 方法 190/190、文档指标 7/7。
- 生产原有两个无任何导入引用的 2026-05 遗留文件 `core/telegram_stats.py`、`core/token_statistics.py` 造成指标 79/77；已移出活动树到本次备份的 `stale_core/`，可恢复。

## 配置、调度与持久化

- 生产 `_CONFIG_VERSION=5.38.0`。
- `MYSTIC_BROADCAST_CONFIG.enabled=true`、`cta_enabled=true`，三档 mode 固定为 `almanac / tarot / iching`。
- `AUTO_NEWS=false`、`NEWS_BROADCAST_CONFIG.enabled=false`。
- 生产发现 45 个 BaseTask、50 个调度项；存在 `mystic_morning / mystic_afternoon / mystic_evening`，`news_*=[]`、旧定向 `tarot_*=[]`。
- 第二次重启后再次验证双服务、health、NRestarts 和配置，结果保持一致。

## 真实 Telegram 回执

- 今日黄历：Rich Message `message_id=2985`，来源 `cnlunar-0.2.4`，唯一按钮为“问 Mory 专属风水”。
- 三张塔罗：Rich Message `message_id=2986`，来源 `curated-major-arcana-v1`，唯一按钮为“看预览与福利”。
- 易经一卦：Rich Message `message_id=2987`，来源 `king-wen-64-v1`，唯一按钮为“自助订阅”。
- 三张均使用生产生成器、生产 Rich formatter 和生产按钮构建器发送给管理员，卡片署名固定 `@MoryMateBot`；未在非计划时段向群聊一次性刷三张测试消息，后续由已注册的三档调度正常投放群聊。

## 结论

代码、依赖、配置、调度、双服务、持久化和真实 Telegram Rich Message 回执已闭环。生产已不再使用截图中的四行模板，也没有恢复任何新闻任务。
