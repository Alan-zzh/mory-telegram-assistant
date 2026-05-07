# Universal AI Router

## 项目介绍

**项目名称**：Universal AI Router（通用AI模型路由系统）

**项目描述**：一个智能的AI模型路由系统，能够自动将请求分发到最合适的AI服务提供商，支持多API对接、多账号轮询、智能路由、成本控制和完善的统计报表功能。

**核心功能**：
- 多API对接：统一接口对接多种AI服务
- 多账号轮询：同一服务商的多个账号自动轮询，避免单账号限流
- 智能路由：根据任务类型自动选择最合适的模型
- 成本控制：支持性能优先、成本优先、平衡模式三种策略
- 统计报表：完善的调用统计，支持多维度成本分析

---

## 特性列表

| 特性 | 说明 |
|------|------|
| 多API源支持 | 通义千问、OpenAI、Claude、Gemini 等主流AI服务 |
| 多账号轮询 | 同一服务商的多个账号自动轮询，支持权重配置 |
| 智能任务分流 | 文字/图像/音频/视频/向量自动识别并路由 |
| 成本控制 | performance（性能优先）/ cost（成本优先）/ balanced（平衡模式） |
| Token统计 | 单次/每日/每周/每月统计，支持成本分析 |
| 配置驱动 | 零代码添加新API和新模型，修改配置文件即可 |
| 熔断机制 | 账号失败自动切换，失败过多暂时隔离 |
| 统一接口 | 告别各平台SDK，统一的chat/image/audio接口 |

---

## 快速开始

### 安装依赖

```bash
pip install requests
```

### 配置API密钥

编辑 `config/router_config.json` 配置文件，添加你的API密钥：

```json
{
  "providers": {
    "qwen": {
      "accounts": [
        {
          "api_key": "your-qwen-api-key-here",
          "enabled": true
        }
      ]
    },
    "openai": {
      "accounts": [
        {
          "api_key": "your-openai-api-key-here",
          "enabled": true
        }
      ]
    }
  }
}
```

### 运行演示

```bash
# 进入项目目录
cd universal_ai_router

# 运行主程序
python -m universal_ai_router.main

# 或直接运行
python main.py
```

### 运行测试

```bash
python -m universal_ai_router.tests.test_router
```

---

## 配置说明

### global 全局配置

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `default_strategy` | string | 默认策略：performance / cost / balanced |
| `enable_fallback` | boolean | 启用备选方案，当前provider失败时自动切换 |
| `log_level` | string | 日志级别：DEBUG / INFO / WARNING / ERROR |

### providers 服务商配置

每个服务商配置包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `api_type` | string | API类型：qwen / openai / claude / gemini |
| `base_url` | string | API地址（可选，覆盖默认地址） |
| `accounts` | array | 账号列表 |
| `round_robin` | boolean | 是否启用轮询 |

### model_pools 模型池配置

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 模型名称 |
| `provider` | string | 服务商标识 |
| `cost_level` | int | 成本等级（1-10，数值越小越便宜） |
| `price` | object | 价格信息：input_price / output_price |

---

## API使用示例

### 基础文字聊天

```python
from universal_ai_router.core import get_universal_ai

# 获取实例
ai = get_universal_ai()

# 文字聊天
result = ai.chat("你好，请介绍一下自己")
print(result)
```

### 带参数的聊天

```python
# 指定模型
result = ai.chat(
    "用Python写一个快速排序",
    model="qwen-max",
    strategy="performance"  # 性能优先
)

# 指定回复长度
result = ai.chat(
    "写一首关于春天的诗",
    model="qwen-max",
    max_tokens=500
)
```

### 图像理解

```python
# 读取图片文件
with open("image.jpg", "rb") as f:
    image_data = f.read()

# 图像理解
result = ai.image(image_data, "请描述这张图片的内容")
print(result)
```

### 语音识别

```python
# 读取音频文件
with open("audio.mp3", "rb") as f:
    audio_data = f.read()

# 语音识别
result = ai.audio(audio_data, "请转录这段音频的内容")
print(result)
```

### 查看统计

```python
from universal_ai_router.core import get_router_statistics

# 获取统计实例
stats = get_router_statistics()

# 今日统计
daily = stats.get_daily_statistic()
print(f"今日调用次数: {daily['total_calls']}")
print(f"今日Token消耗: {daily['total_tokens']}")
print(f"今日成本: ${daily['total_cost']:.4f}")

# 指定日期统计
weekly = stats.get_statistic_by_date("2024-01-07", "2024-01-13")
print(f"周统计: {weekly}")
```

### 高级：直接使用路由功能

```python
from universal_ai_router.core import get_router

router = get_router()

# 根据任务类型和策略选择最优provider
result = router.route(
    task_type="chat",
    strategy="balanced",
    model_hint="qwen-max"
)

# 处理响应
if result["success"]:
    print(result["data"]["content"])
else:
    print(f"请求失败: {result['error']}")
```

---

## 成本策略说明

### performance（性能优先）

优先选择性能最强的模型，不考虑成本。适用于对输出质量要求极高的场景。

### cost（成本优先）

优先选择成本最低的模型，牺牲一定性能。适用于大规模调用、成本敏感的场景。

### balanced（平衡模式）

在性能和成本之间取得平衡，系统自动选择性价比最高的模型。**这是默认策略**。

---

## 架构说明

```
┌─────────────────────────────────────────────────────────────┐
│                      统一接口层 (UniAI)                      │
│                   chat() / image() / audio()                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    智能路由层 (Router)                        │
│         任务识别 + 策略选择 + 模型匹配 + 账号分配              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      模型池 (Model Pools)                    │
│           qwen / openai / claude / gemini                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   API适配层 (API Adapter)                    │
│              统一协议 + 请求封装 + 响应解析                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   账号管理器 (Account Manager)                │
│              轮询分配 + 熔断隔离 + 失败重试                    │
└─────────────────────────────────────────────────────────────┘
```

### 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 统一接口 | `core/uni_ai.py` | 提供chat/image/audio统一入口 |
| 智能路由 | `core/router.py` | 任务分流、模型选择、策略执行 |
| 配置管理 | `core/config_manager.py` | 配置文件加载、配置校验 |
| API适配 | `core/api_adapter.py` | 各平台API协议适配 |
| 账号管理 | `core/account_manager.py` | 多账号轮询、熔断隔离 |
| 统计报表 | `core/router_statistics.py` | 调用统计、成本分析 |
| 数据存储 | `core/router_database.py` | SQLite数据持久化 |

---

## 文件结构

```
universal_ai_router/
├── core/
│   ├── __init__.py              # 模块初始化
│   ├── config_manager.py        # 配置管理：加载、校验、保存
│   ├── api_adapter.py           # API适配器：各平台协议转换
│   ├── account_manager.py       # 账号管理：轮询、熔断、隔离
│   ├── router.py                # 智能路由：任务分流、模型选择
│   ├── uni_ai.py                # 统一接口：chat/image/audio
│   ├── router_database.py       # 数据库：SQLite持久化
│   └── router_statistics.py     # 统计报表：调用统计、成本分析
├── config/
│   └── router_config.json       # 配置文件：全局/服务商/模型池
├── tests/
│   ├── __init__.py
│   └── test_router.py           # 测试用例：路由、统计、熔断
├── data/
│   └── account_states.json       # 账号状态数据
├── docs/
│   └── README.md                # 开发文档
├── main.py                      # 入口文件：演示程序
├── setup.py                     # 安装脚本
└── README.md                    # 项目说明文档
```

---

## 常见问题

### Q: 如何添加新的AI服务商？

编辑 `config/router_config.json`，在 `providers` 中添加新配置：

```json
{
  "providers": {
    "your_provider": {
      "api_type": "openai",  // 参考已有类型
      "base_url": "https://api.your-provider.com",
      "accounts": [
        {
          "api_key": "your-api-key",
          "enabled": true
        }
      ]
    }
  }
}
```

同时在 `model_pools` 中添加对应的模型配置即可，无需修改代码。

### Q: 如何查看各账号的调用情况？

```python
from universal_ai_router.core import get_router_statistics

stats = get_router_statistics()
# 获取详细统计
print(stats.get_daily_statistic())
```

### Q: 某个账号被限流怎么办？

系统内置熔断机制，当账号连续失败达到阈值会自动隔离。隔离期间请求会自动切换到其他可用账号。隔离时间结束后自动恢复尝试。

---

## 许可证

MIT License
