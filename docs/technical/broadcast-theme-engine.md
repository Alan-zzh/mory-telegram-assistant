# 播报主题上下文（现行）

`core/theme_pools.py` 当前只保留主题与语气词池，以及按日期、时段和条目 ID 生成稳定上下文的纯函数。

`modules/scheduled_broadcast.py` 会构造这份上下文，但当前不会把主题、语气或旧版 hint 拼接到播报正文、页脚或按钮。旧版 `slang_hint`、`photo_hint`、`conversion_hint` 模板及 Getter 已删除，防止生硬营销文案重新进入发送链。

现行约束：

- 自定义正文、页脚和按钮仍是实际发送内容的真相源。
- 主题上下文不得绕过 CTA 互斥规则，也不得自行追加销售入口。
- 若未来重新用于 AI Prompt，必须先补“上下文被真实消费”的调用链测试和正常反例。
- 旧机制与示例已移至 `docs/archive/broadcast-theme-engine-v5.19.md`，不再代表运行态。
