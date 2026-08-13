---
schema: "puzan.active-handoff/v2"
handoff_id: "hof_ce0d0f76f92c2d4bd765"
task_fingerprint: "fp_12f9002b780e7013a6b92e28"
project_id: "prj_4b071279531a6f2bf65f"
project_name: "mory_assistant"
status: "active"
task_state: "not_started"
trigger_reasons: ["long_task"]
target_files: ["core/message_dispatcher.py", "core/handlers/ai_reply_handler.py", "core/mory_bot.py", "core/start_welcome_card.py"]
host_refs: ["codex/desktop"]
created_at: "2026-08-14T01:16:59+08:00"
updated_at: "2026-08-14T01:16:59+08:00"
revision: 1
generation: 1
last_receipt_id: null
redaction_schema: "puzan-redact/v1"
---

# Handoff

## Goal
- 群聊纯点名随机发无销售按钮图片卡，带问题直接处理，回复消息继续承接，并完成生产真实回执。

## Constraints
- 群聊每轮至多一个与意图一致的入口
- 纯点名不推销
- 群聊图片进入 reply_tracking

## Completed
- 尚未完成可验证事项。

## Current Step
- 本地完成，准备提交和部署

## Pending
- 提交 v5.38.52
- 部署并取得群聊真实回执

## Decisions
- 复用三款 v2 欢迎底图，不生成第二套视觉真相源
- 群聊纯点名不带私聊双销售按钮

## Files
- core/message_dispatcher.py — planned
- core/handlers/ai_reply_handler.py — planned
- core/mory_bot.py — planned
- core/start_welcome_card.py — planned

## Verification
- 尚未运行验证；完成前必须补充真实命令、结果和退出码。

## Next Action
- 运行发布门禁，部署后从真实群聊入口探针

## Suggested Skills
- mory-assistant-maintenance
- deploy-automation

## Completion History
- 尚无根任务完成回执。

## Revision Log
- 2026-08-14T01:16:59+08:00 r1 created triggers=long_task
