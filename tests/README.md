# Mory小助理 测试目录

> **最后整理**：2026-06-02（v5.12.1 根目录 47 个 `_*.py` 文件归档至此）
> **总原则**：所有测试代码统一放 `tests/`，根目录**禁止**出现 `_*.py` 临时测试文件
> **详细规范**：[AGENTS.md](../AGENTS.md) F1 铁律

---

## 📁 目录结构

```
tests/
├── README.md           # 本文件
├── _archive/           # 历史归档（v5.12.1 之前根目录 47 个 _*.py 临时文件）
├── integration/        # 集成测试（端到端、多模块协作）
└── unit/               # 单元测试（单函数/单模块）
```

## 📦 _archive/ 归档内容

- **来源**：根目录 47 个 `_*.py`（`v5.12.0 之前`临时诊断/测试文件）
- **原因**：违反 F1 铁律（测试在 `tests/`、根目录禁临时文件）
- **保留策略**：**只读**（不再修改/运行）
- **典型文件**：
  - `_check_vps.py` ~ `_check_vps16.py`（VPS 配置/状态检查）
  - `_test_*.py`（临时功能验证）
  - `_read_log*.py`（日志读取）
  - `_cleanup_ads.py` / `_debug_ad.py`（广告检测调试）
  - `_verify_deploy.py` / `_deploy_fix.py`（部署验证）
  - `_delete_ads*.py` / `_manual_burn.py`（消息删除）
  - `_task1_survey.py`（任务调研）
- **完整列表**：`Get-ChildItem tests/_archive/`

## 🆕 新测试如何写？

| 类型 | 位置 | 命名 |
|------|------|------|
| 单元测试 | `tests/unit/test_xxx.py` | `test_xxx.py` |
| 集成测试 | `tests/integration/test_xxx_integration.py` | `test_xxx_integration.py` |
| 端到端验证 | `tests/integration/verify_xxx.py` | `verify_xxx.py` |

> **注意**：端到端验证脚本也可放在 `scripts/`（如 `scripts/verify_orphan_cleanup.py`），按 F2 铁律。

## ⚠️ 不要再做的事

- ❌ 根目录写 `_test_xxx.py` / `_check_xxx.py` / `_debug_xxx.py`
- ❌ 在 `tests/_archive/` 里修改/运行旧文件
- ❌ 把测试放在 `scripts/` 目录（除非叫 `verify_*` 端到端脚本）

## 🔗 相关

- [AGENTS.md](../AGENTS.md) F1 铁律（测试位置）
- [AGENTS.md](../AGENTS.md) F2 铁律（工具脚本位置）
- [AGENTS.md](../AGENTS.md) F5 铁律（根目录禁临时文件）
- [scripts/verify_orphan_cleanup.py](../scripts/verify_orphan_cleanup.py) — 端到端验证样例
