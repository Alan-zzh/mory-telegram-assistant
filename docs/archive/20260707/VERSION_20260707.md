v5.31.2

2026-07-06 Hotfix（审计整改）：项目自检与架构优化审计 12 项 Task + 4 项 Bug 修复 + 6 项 P1 暗病 + 4 项 P2 暗病全部修复完成。新增 LLM 全局 24h 熔断 / executemany 批量化 / sha256 密码哈希 / Alembic 环境变量覆盖 / Session 滑动续期 / SSH Key 优先认证 / CST 时区统一 / WriteQueue 死锁检测 / scheduler_monitor job_id 修正等。零暗病、零下一步计划。

2026-07-06 Hotfix：所有单人禁封管理员通知必须带“一键解封”按钮。广告处置、编辑消息广告检测、全局黑名单入群拦截均接入 `ad_unban:<uid>:<chat_id>` 回调。

2026-07-06 Hotfix：解封入口三次加固。`main.py` 已在兜底分发器之前注册 `/unban` 专用 handler；`/unban 8383136504` 与 `/unban @mmb3695` 线上只读 smoke 均解析到 8383136504；同名显示名“萌萌逼”会返回候选 ID，不盲选。

2026-07-06 Hotfix：修复解封指令私聊不生效。`/unban`、`/解封`、`解封 ...`、`解除封禁...` 已前移到消息分发 P5.6 早路由，私聊和群聊都会优先执行完整解封链；已恢复生产用户 8383136504 的 Telegram 群权限。

2026-07-06 Hotfix：彻底修复“签到”误封。签到/打卡/checkin 等正常业务动作不再进入广告资料层和延迟封禁累计；解封统一清 blacklist/global_blacklist/mute_records/ad_suspicious_users，并支持 /unban ID、/unban @username、回复消息解封、私聊自助解封和按钮解封。

2026-07-06 Hotfix：修复广告资料层误封风险。白名单/群管理员免检前移到 Bio/emoji 状态检测之前；广告处置管理员通知新增“解封”按钮，可一键移除 blacklist/global_blacklist/mute_records 并恢复群内发言权限。

2026-07-05 Hotfix：取消 AI 失败时的拟人化尴尬兜底。普通/未知/特殊模式全失败直接静默，转化/联系模式失败只给 @moryselect 与 @MorychannelBot 固定入口。

2026-07-05 Hotfix：修复 AI 真实失败根因。剔除慢/坏模型，standard 首发 glm-5.1，light/premium 首发 qwen3.7-max-2026-05-17/06-08；生产 AI 调用预算收紧为 30 秒、2 次。
