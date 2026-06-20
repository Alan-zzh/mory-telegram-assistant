# 代码质量扫描工具使用指南

## 功能说明

`scripts/code_quality_scan.py` 提供两项代码质量检测功能：

1. **vulture** - 检测未使用的代码（函数、类、变量、导入）
2. **radon** - 分析圈复杂度，识别高复杂度模块

## 安装依赖

```powershell
# 安装 vulture 和 radon
pip install vulture>=2.0 radon>=5.1.0

# 或者从 requirements.txt 安装
pip install -r requirements.txt
```

## 基本用法

### 1. 扫描全部（推荐）

```powershell
python scripts/code_quality_scan.py
```

同时运行 vulture 和 radon，生成完整报告。

### 2. 仅扫描未使用代码

```powershell
python scripts/code_quality_scan.py --vulture
```

### 3. 仅扫描圈复杂度

```powershell
python scripts/code_quality_scan.py --radon
```

### 4. 自定义阈值

```powershell
# 设置 vulture 置信度阈值（0-100），只显示高置信度的未使用代码
python scripts/code_quality_scan.py --threshold 60

# 设置圈复杂度阈值（默认 10），只标记复杂度 >= 15 的函数
python scripts/code_quality_scan.py --cc-threshold 15
```

### 5. 输出到文件

```powershell
# 生成 Markdown 格式报告
python scripts/code_quality_scan.py --output code_quality_report.md

# 指定绝对路径
python scripts/code_quality_scan.py --output C:\temp\report.md
```

## 白名单配置

某些代码虽然看起来"未使用"，但实际上是通过动态调用、装饰器注册、框架回调等方式使用的。这些应该添加到 `.vulture_whitelist` 文件中，避免误报。

### 白名单文件格式

`.vulture_whitelist` 是 Python 文件，可以直接引用名称：

```python
# 动态调用的函数
register_member_handlers
register_callback_handlers

# 回调函数
callback_handler
on_message

# 魔术方法
__init__
__str__
__call__
```

### 常见需要白名单的场景

1. **装饰器注册的函数**：
   - `@bot.callback_query_handler` 注册的回调
   - `@app.route` 注册的 Flask 路由
   - `@event.listens_for` 注册的 SQLAlchemy 事件

2. **动态加载的模块**：
   - 通过 `importlib` 动态导入的模块
   - 通过配置动态启用的功能函数

3. **框架约定的命名**：
   - pytest 的 `setup_module`、`teardown_class` 等
   - 上下文管理器的 `__enter__`、`__exit__`
   - 属性访问器的 `@property`、`@setter`

4. **通用回调模式**：
   - `on_complete`、`on_error`、`on_success`
   - `handler`、`listener`、`observer`

## 报告解读

### vulture 报告

```
## 未使用代码（vulture）

共检测到 **15** 处未使用代码：

### 未使用函数（10 处）

| 文件 | 行号 | 名称 | 置信度 |
|------|------|------|--------|
| `core/handlers/callback_handlers.py` | 45 | `old_callback` | 100% |
```

**解读**：
- **置信度 100%**：几乎确定未使用，可以安全删除
- **置信度 60-99%**：很可能未使用，建议人工确认
- **置信度 <60%**：可能是误报，检查是否动态调用

### radon 报告

```
## 圈复杂度分析（radon）

复杂度阈值：**10**（超过此值的函数被标记）

### 高复杂度函数（5 个）

| 文件 | 行号 | 函数名 | 类型 | 复杂度 | 等级 |
|------|------|--------|------|--------|------|
| `core/message_dispatcher.py` | 120 | `dispatch_message` | function | **25** | C |
```

**复杂度等级**：
- **A (1-5)**：简单，易于维护 ✅
- **B (6-10)**：中等复杂度，可接受 ✅
- **C (11-20)**：较高复杂度，建议重构 ⚠️
- **D (21-30)**：高复杂度，强烈建议重构 ⚠️
- **E (31-50)**：非常高复杂度，必须重构 ❌
- **F (>50)**：无法维护，立即重构 ❌

## 最佳实践

### 1. 定期扫描

```powershell
# 每周运行一次，生成报告
python scripts/code_quality_scan.py --output reports\weekly_$(Get-Date -Format 'yyyyMMdd').md
```

### 2. 渐进式改进

- **第一阶段**：只关注置信度 100% 的未使用代码
- **第二阶段**：处理复杂度 >20 的函数
- **第三阶段**：处理复杂度 >10 的函数

### 3. 维护白名单

发现误报时，及时添加到 `.vulture_whitelist`：

```python
# 在 .vulture_whitelist 中添加
my_dynamic_function
my_callback_handler
```

### 4. 代码审查时参考

提交 PR 前运行扫描，确保没有引入：
- 未使用的导入
- 未使用的高复杂度函数

## 扫描范围

**包含**：
- `core/` - 核心业务逻辑
- `dashboard/` - Dashboard 后端
- `modules/` - 功能模块
- `scripts/` - 脚本工具
- 根目录 `.py` 文件

**排除**：
- `tests/` - 测试代码
- `migrations/` - 数据库迁移
- `docs/` - 文档
- `.git/`、`__pycache__/`、`venv/` 等

## 常见问题

### Q: 为什么某些函数被标记为"未使用"，但实际上在用？

A: vulture 无法识别动态调用模式（如装饰器注册、反射调用）。解决方法：
1. 确认是误报后，添加到 `.vulture_whitelist`
2. 使用 `--threshold 60` 过滤低置信度结果

### Q: 圈复杂度多少算合理？

A: 
- 单个函数复杂度 <=10：良好
- 11-20：可接受，但建议重构
- >20：强烈建议拆分

### Q: 可以自动删除未使用代码吗？

A: **不建议自动删除**。本工具仅生成报告供人工审查，因为：
1. 可能是动态调用，vulture 无法识别
2. 可能是预留接口，未来会使用
3. 自动删除可能导致运行时错误

## 技术细节

- **扫描策略**：递归扫描目录，排除测试和迁移文件
- **白名单机制**：vulture 原生支持，通过 `.vulture_whitelist` 文件引用名称
- **报告格式**：Markdown 表格，便于阅读和分享
- **性能**：扫描整个项目通常在 10-30 秒内完成

## 相关文档

- [vulture 官方文档](https://github.com/jendrikseipp/vulture)
- [radon 官方文档](https://radon.readthedocs.io/)
- [圈复杂度说明](https://en.wikipedia.org/wiki/Cyclomatic_complexity)
