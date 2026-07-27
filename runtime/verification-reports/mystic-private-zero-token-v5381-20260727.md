# v5.38.1 传统文化播报与私聊零 Token 验证

日期：2026-07-27  
可信提交：`2718906cc312fe487d7513c51b4d496544fba44e`  
生产备份：`/home/ubuntu/mory_assistant/backups/deploy_v5381_20260727_190708`

## 本地门禁

- `python -m pytest -q`：496 passed / 7 skipped。
- `python scripts/verify_db_methods.py`：190 个委托方法，无缺失、无孤儿。
- `python scripts/doc_consistency.py`：7 项全部 OK。
- `python -m py_compile` 与 `git diff --check`：通过。
- 系统级 Python 的 `pip check` 仍报告多个既有跨项目依赖冲突；本次未修改依赖，业务锁文件与测试环境不受影响。

## 生产部署

- 仅增量发布 15 个运行/文档文件；生产 `config.json` 以线上原文件为基准，只更新 `_CONFIG_VERSION=5.38.1` 和 `MYSTIC_BROADCAST_CONFIG.private_reply_enabled=true`。
- 未上传或覆盖 `.env`、`mory.db`、本地 `config.json`。
- `mory-assistant`、`mory-dashboard`：active + enabled，NRestarts 均为 0。
- `/api/health`：`{"status":"ok","version":"v5.38.1"}`。
- 8 个关键运行文件本地与生产 SHA-256 一致。
- 生产 DB 方法 190/190，文档数字 7/7；当前进程自 19:08 起无 traceback、exception、critical 或 error。

## 真实业务回执

- 黄历 Rich Message：2990，CTA `contact`。
- 塔罗 Rich Message：2991，CTA `preview`。
- 易经 Rich Message：2992，CTA `subscribe`。
- 三张卡片均由生产格式化与发送链生成，未出现 `※`、`不替代`、`传统民俗参考`、`不作确定性断言` 或 `绝对答案`。
- 私聊 `/算卦 工作` 经生产 `KeywordTrigger` 早路由发送：消息 2993；处理结果 `handled=true`，遥测 `ai_mode=local_zero_token`，`token_usage=0`，AI Spy 未被调用。
- 生产探针：同一用户同日同主题一致、跨日变化、普通“你怎么看易经文化”不被占卜早路由抢答。
