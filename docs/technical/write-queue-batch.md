# WriteQueue 批量化与死锁检测详解

> 本文档为独立技术说明，未被 AGENTS.md 直接索引 · 适用版本：v5.23.0+ / v5.31.2 审计整改
> **最后更新**：2026-07-06

## 概述

`core/write_queue.py` 是 SQLite 单线程写入队列，所有写操作投递到内存队列由后台 Worker 串行执行，彻底消除 `database is locked`。本文档详述 v5.31.2 审计整改的两项关键修复：**executemany 批量化**（10x 性能修复）和 **Worker 死锁检测**（防自死锁）。

> **【历史演进说明】** 本文档描述的批量化/死锁检测实现属于 **v5.23.0–v5.31.2 时期**。v5.32.0 起 `core/write_queue.py` 已降级为空壳兼容层（WAL + busy_timeout=30s + synchronous=NORMAL 已足够，WriteQueueConnectionProxy 移除），`enqueue / enqueue_batch / enqueue_and_wait` 均抛 `RuntimeError` 提示直接使用 `db.conn.execute()/executemany()`；文中 `_WriteTask` / `_execute_task` / `_worker_thread_id` / `is_executemany` / `_FakeCursorForBatch` 均已不存在，调用方 `core/db_connection_proxy.py` 已于 **v5.38.10 删除**。下文代码示例仅为历史实现还原，不适用于现行代码。

## 适用场景

- 排查"批量 INSERT 性能慢"时查阅
- 新增批量写场景时参考 `enqueue_batch` 用法
- 排查 `Deadlock risk detected` 日志时查阅
- 理解 WriteQueue 内部任务执行流程时查阅

## executemany 批量化（P0 Task-02）

### 问题

历史版本 `core/write_queue.py` 的 executemany 代理（原 `core/db_connection_proxy.py` 文件已于 v5.38.10 删除）之前逐条入队：

```python
# 旧实现（性能损失 10x+）
for params in params_seq:
    write_queue.enqueue(self._real, sql, params)  # 每条单独入队
```

10 条批量写会产生 10 个 `_WriteTask`，Worker 串行执行 10 次 `conn.execute` + 10 次 `commit`，性能损失 10x+。

### 修复

新增 `WriteQueue.enqueue_batch(conn, sql, params_seq, is_critical)`：

```python
# 新实现（一次性投递）
write_queue.enqueue_batch(self._real, sql, params_list, is_critical=is_critical)
```

整个 `params_seq` 一次性入队为单个 `_WriteTask(is_executemany=True)`，Worker 在 `_execute_task` 中调用 `conn.executemany(sql, params)` 一次完成批量写。

### _WriteTask 扩展

```python
class _WriteTask:
    __slots__ = (..., "is_executemany")  # 新增字段

    def __init__(self, conn, sql, params, callback=None, future=None, is_executemany=False):
        ...
        self.is_executemany = is_executemany
```

### _execute_task 分支

```python
def _execute_task(self, task):
    if task.is_executemany:
        cur = task.conn.executemany(task.sql, task.params)  # 批量执行
    else:
        cur = task.conn.execute(task.sql, task.params)       # 单条执行
    task.conn.commit()
    ...
```

### _FakeCursorForBatch

批量写异步入队后立即返回，rowcount 无法预知（Worker 异步执行）。`_FakeCursorForBatch` 设 `rowcount=-1` 表示"批量写已投递，行数未知"，符合 PEP 249 executemany 语义。

## Worker 死锁检测（Bug-04）

### 问题

`enqueue_and_wait` 是同步等待 API：投递任务后阻塞当前线程等待 Worker 执行完毕。如果**在 Worker 线程内部**调用 `enqueue_and_wait`，Worker 会等待自己处理任务，永久阻塞。

之前代码只在注释中警告"不要在 Worker 线程内调用"，没有运行时检测，新代码容易踩坑。

### 修复

`WriteQueue` 新增 `_worker_thread_id` 字段，在 `_run_loop` 入口记录 Worker 线程 ident：

```python
def _run_loop(self):
    self._worker_thread_id = threading.get_ident()  # 在 Worker 内部记录
    logger.info("🔄 DBWriteWorker 开始消费队列")
    ...
```

`enqueue_and_wait` 检测当前线程是否是 Worker：

```python
def enqueue_and_wait(self, conn, sql, params=(), ...):
    # 死锁检测
    if self._worker_thread_id is not None and \
       threading.get_ident() == self._worker_thread_id:
        err = RuntimeError("Deadlock risk detected: enqueue_and_wait called from DBWriteWorker thread")
        result.error = err
        logger.error(f"🚨 {err} | SQL: {sql[:80]}")
        return result
    ...
```

### 关键细节：ident 时序问题

不能在 `start()` 中通过 `self._worker.ident` 记录，因为线程 `ident` 在 `start()` 后可能仍是 `None`（线程未真正运行）。必须在 `_run_loop` 内部通过 `threading.get_ident()` 记录，确保拿到真实 ident。

## 背压机制（v5.25.0 阶段1-B，已存在）

`enqueue_batch` 也支持背压分类降级：

- `is_critical=True`：队列满抛 `WriteQueueFullError`，由上层降级处理
- `is_critical=False`：队列满静默丢弃 + 低频警告（每 30s 最多一条）

核心表（`user_profiles` / `funnel_state` / `conversion_events`）的写入默认 `is_critical=True`，非核心表默认 `False`。

## 单元测试

`tests/unit/test_audit_fixes.py::TestEnqueueBatch` 覆盖：
- 未启动队列回退同步 executemany
- 空参数序列处理
- 已启动队列正确入队 `_WriteTask(is_executemany=True)`
- 队列满 + `is_critical=True` 抛 `WriteQueueFullError`
- 队列满 + `is_critical=False` 静默丢弃返回 False

## 相关文件

- `core/write_queue.py` — 现行实现为 v5.32.0 降级后的空壳兼容层：`start()/stop()` no-op、`get_stats()` 返回零值（监控代码依赖）、`enqueue/enqueue_batch/enqueue_and_wait` 抛 `RuntimeError` 提示直接用 `db.conn.execute()/executemany()`
- `core/db_connection_proxy.py` — 已删除（v5.38.10）；历史调用方（`executemany` 代理）
- `tests/unit/test_audit_fixes.py` — 单元测试（历史批量化测试）
