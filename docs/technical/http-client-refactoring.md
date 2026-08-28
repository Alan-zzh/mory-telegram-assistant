# HTTP 请求安全与可靠性

> 当前行为以 `core/http_client.py` 为准；本页只说明长期边界，不复制易漂移的调用清单。

## 统一入口

- 普通外部 HTTP 调用优先复用 `core.http_client.get_http_client()`。
- 每个调用必须设置有界超时；业务失败应返回可诊断结果或显式抛错，不静默吞掉。
- 请求 URL 与异常在写日志前统一脱敏，查询串中的 key、token、secret、password 等值不得进入日志。

## 重试边界

- GET、HEAD、OPTIONS 可按配置重试。
- POST 等可能产生远端写入的请求默认不重试，因为超时并不能证明服务端没有执行。
- 只有调用方已经提供幂等键或等价去重保障时，才可显式传入 `retry_unsafe=True`。
- Telegram 发消息、Telegraph 创建页面、模型推理等写操作不得因连接结果不确定而自动重发。

## 配置

`HTTP_CLIENT_CONFIG` 可设置默认 timeout、retry_times、retry_delay、日志开关和服务级超时。密钥只从 `.env`/进程环境注入，不能写入该配置组。

## 验证

```powershell
python -m pytest tests/unit/test_external_write_retry_policy.py tests/unit/test_http_optional_failure_logging.py -q
python -m compileall -q core/http_client.py modules/weather.py modules/telegraph.py core/ai_media_tools.py
```

旧 v5.17 设计说明保存在 `docs/archive/http-client-refactoring-v5.17.md`，仅作历史背景，不代表当前运行合同。
