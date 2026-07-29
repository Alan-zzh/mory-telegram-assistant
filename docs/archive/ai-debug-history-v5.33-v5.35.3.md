# AI 排错归档：v5.33.0—v5.35.3

> 从根目录 `AI_DEBUG_HISTORY.md` 归档；归档日期：2026-07-30。

## 结构性风险（推断，附依据）

- 历史误封集中在“检测链与入口/清理链不一致”类问题。推断系统存在“新增能力未同步接入统一入口/清理”的结构性风险。所有新增检测/播报必须显式接入 dispatcher 与 burn_orphan，并加回归测试固化。

### 9. Dashboard worker timeout

- 问题：生产 Dashboard 曾连续出现 Gunicorn `WORKER TIMEOUT` / `SIGKILL`。
- 根因：默认 30 秒 timeout 无法容纳数据库、SSH、审计等慢操作。
- 解法：systemd 增加 `--timeout 120 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100`。
- 预防：慢接口必须设置应用层 timeout，巡检抽查 Dashboard journal。

### 10. 同机浏览器容器拖垮 Mory

- 问题：同机 Chromium 占用大量内存并触发 OOM，连带 Dashboard timeout。
- 根因：`dreamina-bridge` 容器缺少有效内存上限。
- 解法：重启释放内存，并限制容器 memory / memory-swap。
- 预防：巡检同时检查内存、容器资源、OOM 和 Dashboard journal，不能只看双服务 active。

### 11. Rich Message 400

- 问题：Telegram 返回 `object expected as rich message`。
- 根因：代码传入组件列表，接口需要 `InputRichMessage` 对象。
- 解法：字符串或列表统一包装成 `{"html": "..."}`，字典保持原样。
- 预防：新 Bot API 能力先核对官方参数类型。

### 12. 解封链路不对称

- 问题：解封后仍可能再次触发禁封。
- 根因：禁封未写 `mute_records`，解封未清 `ad_suspicious_users`，数据库清理又依赖已丢失的内存状态。
- 解法：禁封写入、解封清理和管理员通知三条链对称处理。
- 预防：写入什么表，解封就清理什么表；数据库兜底不能依赖内存条件。

### 13. SQLite 新列使用非常量默认值

- 问题：`ALTER TABLE ADD COLUMN ... DEFAULT CURRENT_TIMESTAMP` 导致服务启动崩溃循环。
- 根因：SQLite 不允许 `ADD COLUMN` 使用非常量默认值。
- 解法：新列允许 NULL，由业务写入时显式赋 `CURRENT_TIMESTAMP`。
- 预防：新增列只用常量默认值，部署后验证服务没有重启循环。

### 14. AI 模型黑名单重启丢失

- 问题：内存黑名单不落盘，多池重复刷拉黑日志。
- 根因：保存任务只关注模型索引变化，未关注黑名单变化。
- 解法：增加线程安全 dirty 标记，索引或黑名单任一变化都触发落盘；多池拉黑前判重。
- 预防：运行态配置变更必须有明确的脏标记和异步落盘机制。

### 15. v5.35.0 新模块 SQL 三类错误

- 问题：表名复数漂移、引用不存在表、`INSERT OR REPLACE` 缺 NOT NULL 字段。
- 根因：模块未以 `_init_tables()` 为数据库真相源，也未验证真实读写。
- 解法：统一真实表名、补齐实际需要的表，并让 REPLACE 路径覆盖必要字段。
- 预防：新增模块必须完成 import、数据库启动、表名扫描和读写往返测试。

### 16. `fetchone()` 调用两次

- 问题：统计和健康度恒为 0。
- 根因：三元表达式条件和取值分别调用 `cursor.fetchone()`，第一调用已消费结果。
- 解法：先保存 `row = cursor.fetchone()`，再读取 `row[0] if row else 0`。
- 预防：游标读取只调用一次并保存结果。

### 17. `datetime.datetime.timedelta` 引用错误

- 问题：调用 `datetime.timedelta` 抛 AttributeError。
- 根因：`datetime` 实际是由 `from datetime import datetime` 导入的类，不是模块。
- 解法：显式导入并直接使用 `timedelta`。
- 预防：统一 `from datetime import datetime, timedelta`。

### 18. v5.35.2 修复不完全

- 问题：仍残留 fetchone、import、`eval` 和 logger 等 P0 问题。
- 根因：只依赖已有单测，没有静态审计和变更逐项核对。
- 解法：补齐遗漏，`eval` 改为 `ast.literal_eval`，并执行静态审计、编译、文档、DB 和全量测试门禁。
- 预防：CHANGELOG 声明必须与真实 diff 一一对应，重大版本不能只以已有单测作为验收。
