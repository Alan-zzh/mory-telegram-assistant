# 压测落地与背压阈值调优指南

> v5.26.0 阶段1-B | 2C4G VPS + SQLite WAL 环境下的三档梯度压测方案

## 1. 目标

- 提取 SQLite WriteQueue 背压黄金阈值
- 验证乐观锁冲突重试成功率
- 记录 WriteQueueFullError 首次抛出时的队列堆积长度
- 为数据库迁移决策提供客观数据支撑

## 2. 前置准备

### 2.1 Staging 环境

克隆生产 VPS 环境（2C4G），部署当前 v5.26.0：

```bash
# 在 Staging VPS 上
git clone <repo> /opt/mory_assistant
cd /opt/mory_assistant
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install locust  # 压测工具
```

### 2.2 安装 Locust

```bash
pip install locust
```

## 3. 三档梯度压测

### 3.1 一档：只读为主（20 QPS）

**目的**：验证 Dashboard 读取与常规消息分发性能。

```bash
locust -f tests/load/locustfile.py --host http://localhost:6616 \
  --headless -u 20 -r 20 -t 60s --only-summary \
  --html logs/load_test_tier1.html --csv logs/load_test_tier1
```

**预期**：
- P95 < 200ms
- 错误率 < 1%
- 不触发 WriteQueueFullError

### 3.2 二档：读写混合（100 QPS）

**目的**：模拟 22:30 定时播报后，多群组同时高频互动。

```bash
locust -f tests/load/locustfile.py --host http://localhost:6616 \
  --headless -u 100 -r 50 -t 120s --only-summary \
  --html logs/load_test_tier2.html --csv logs/load_test_tier2
```

设置写操作比例：

```bash
export LOAD_TEST_WRITE_RATIO=0.3  # 30% 写操作
```

**预期**：
- P95 < 500ms
- 错误率 < 5%
- 可能开始出现乐观锁冲突，但重试应成功

### 3.3 三档：极限压测（300 QPS）

**目的**：持续向写操作 API 灌流量，直至出现 WriteQueueFullError。

```bash
locust -f tests/load/locustfile.py --host http://localhost:6616 \
  --headless -u 300 -r 100 -t 180s --only-summary \
  --html logs/load_test_tier3.html --csv logs/load_test_tier3
```

设置高写比例：

```bash
export LOAD_TEST_WRITE_RATIO=0.5  # 50% 写操作
```

**预期**：
- P95 可能 > 1000ms
- 错误率可能 > 10%
- 应触发 WriteQueueFullError

## 4. 黄金指标提取

### 4.1 自动分析

```bash
# 分析所有档位
python -m tests.load.analyze_results --all

# 分析指定档位
python -m tests.load.analyze_results --tier 2
```

报告输出到 `logs/load_test_analysis_report.md`。

### 4.2 关键指标

| 指标 | 良好 | 可接受 | 临界 |
|------|------|--------|------|
| P95 延迟 (ms) | < 200 | < 500 | < 1000 |
| 错误率 | < 1% | < 5% | < 10% |
| WriteQueue 队列上限 | 100 | 300 | 500 |
| 乐观锁重试次数 | 3 | 3 | 5 |

## 5. 背压阈值调优

### 5.1 WriteQueue 队列上限

**位置**：`core/write_queue.py` 的 `maxsize` 参数

**调优规则**：
- 若 2 档（100 QPS）未触发 WriteQueueFullError，保持当前值 500
- 若 3 档（300 QPS）首次触发，记录当时的队列堆积长度，将上限设为该值的 80%
- 例如：3 档在队列堆积到 350 时首次抛出 WriteQueueFullError，则将 maxsize 设为 280

### 5.2 乐观锁重试次数

**位置**：`core/shared_db.py` 的乐观锁重试逻辑

**调优规则**：
- 若 2 档冲突率 > 10%，从 3 次调整为 5 次
- 若 3 档冲突率 > 30%，考虑迁移到 Postgres（参考 `docs/technical/db-migration-blueprint.md`）

### 5.3 配置修改后验证

```bash
# 语法验证
python -m py_compile core/write_queue.py core/shared_db.py

# VPS 部署验证
systemctl status mory-assistant mory-dashboard
curl localhost:6616/api/health
```

## 6. 数据库迁移决策

基于压测结果判断是否需要迁移到 Postgres：

| 指标 | 阈值 | 动作 |
|------|------|------|
| max_write_qps_last_24h | > 80 | 触发预警 |
| sqlite_file_size_gb | > 8.0 | 触发预警 |
| average_write_queue_delay_seconds | > 2.0 | 触发预警 |
| 3 档 WriteQueueFullError 首次出现时 QPS | < 150 | 建议迁移 |

**注意**：绝不自动迁移，仅触发告警，人工执行 `docs/technical/db-migration-blueprint.md` 中的 5 阶段方案。

## 7. 注意事项

1. **压测环境隔离**：必须在 Staging 环境执行，禁止在生产环境压测
2. **数据备份**：压测前备份 Staging 数据库
3. **监控并行**：压测时同步观察 `htop`、`iostat`、`systemctl status` 确认资源瓶颈
4. **渐进加压**：从 1 档开始，确认无问题后再升档
5. **结果归档**：压测报告保存到 `logs/load_test_analysis_report.md`，供后续对比
