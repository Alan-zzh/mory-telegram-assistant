#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
代码质量扫描工具 - 检测未使用代码 + 圈复杂度分析

功能：
1. 使用 vulture 扫描未使用的函数、类、变量、导入
2. 使用 radon 分析圈复杂度，识别高复杂度模块
3. 生成结构化报告供人工审查

使用方式：
    python scripts/code_quality_scan.py              # 扫描全部
    python scripts/code_quality_scan.py --vulture    # 仅扫描未使用代码
    python scripts/code_quality_scan.py --radon      # 仅扫描圈复杂度
    python scripts/code_quality_scan.py --threshold 15  # 自定义复杂度阈值
    python scripts/code_quality_scan.py --output report.md  # 输出到文件

依赖：
    pip install vulture>=2.0 radon>=5.1.0
"""

import argparse
import io
import os
import sys
import time
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
WHITELIST_FILE = PROJECT_ROOT / ".vulture_whitelist"

# 默认扫描目录（排除测试、迁移、文档等）
SCAN_DIRS = ["core", "dashboard", "modules", "scripts"]
EXCLUDE_DIRS = {"tests", "migrations", "docs", ".git", "__pycache__", "venv", "node_modules"}

# 默认圈复杂度阈值
DEFAULT_CC_THRESHOLD = 10


def get_scan_paths():
    """获取需要扫描的目录列表"""
    paths = []
    for d in SCAN_DIRS:
        p = PROJECT_ROOT / d
        if p.is_dir():
            paths.append(str(p))
    # 也扫描根目录下的 .py 文件
    for f in PROJECT_ROOT.glob("*.py"):
        paths.append(str(f))
    return paths


def get_exclude_dirs():
    """获取排除目录列表"""
    return list(EXCLUDE_DIRS)


def run_vulture_scan(threshold: int = 0) -> list[dict]:
    """
    使用 vulture 扫描未使用代码

    Args:
        threshold: 最小置信度阈值 (0-100)，默认 0 显示所有

    Returns:
        未使用代码条目列表
    """
    try:
        from vulture import Vulture
    except ImportError:
        print("[错误] vulture 未安装，请运行: pip install vulture>=2.0")
        sys.exit(1)

    v = Vulture()
    scan_paths = get_scan_paths()
    exclude = get_exclude_dirs()

    # 加载白名单
    whitelist_path = str(WHITELIST_FILE)
    if WHITELIST_FILE.exists():
        v.scan(whitelist_path)

    # 扫描项目代码
    for p in scan_paths:
        if os.path.isfile(p):
            v.scan(p)
        else:
            v.scan(p, exclude=exclude)

    # 收集结果
    results = []
    # 获取所有未使用项并过滤
    unused_items = v.get_unused_code(min_confidence=threshold)

    for item in unused_items:
        results.append({
            "type": item.typ,           # 类型：function/class/variable/import/attribute
            "name": item.name,          # 名称
            "file": str(item.filename), # 文件路径
            "line": item.first_lineno,  # 行号
            "confidence": item.confidence,  # 置信度
        })

    # 按文件路径和行号排序
    results.sort(key=lambda x: (x["file"], x["line"]))
    return results


def run_radon_scan(cc_threshold: int = DEFAULT_CC_THRESHOLD) -> dict:
    """
    使用 radon 分析圈复杂度

    Args:
        cc_threshold: 圈复杂度阈值，超过此值的函数会被标记

    Returns:
        包含 cc_results（高复杂度函数列表）和 module_results（模块级统计）的字典
    """
    try:
        from radon.complexity import cc_visit, cc_rank
        from radon.visitors import ComplexityVisitor
    except ImportError:
        print("[错误] radon 未安装，请运行: pip install radon>=5.1.0")
        sys.exit(1)

    cc_results = []  # 高复杂度函数
    module_results = []  # 模块级统计

    scan_paths = get_scan_paths()
    exclude = get_exclude_dirs()

    for base_path in scan_paths:
        if os.path.isfile(base_path):
            py_files = [base_path]
        else:
            py_files = []
            for root, dirs, files in os.walk(base_path):
                # 排除不需要的目录
                dirs[:] = [d for d in dirs if d not in exclude]
                for f in files:
                    if f.endswith(".py"):
                        py_files.append(os.path.join(root, f))

        for filepath in py_files:
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
                    source = fh.read()

                # 圈复杂度分析
                blocks = cc_visit(source)
                # 过滤超过阈值的函数
                high_cc = [b for b in blocks if b.complexity >= cc_threshold]

                for block in high_cc:
                    # 获取复杂度等级名称
                    rank = cc_rank(block.complexity)
                    cc_results.append({
                        "file": filepath,
                        "line": block.lineno,
                        "name": block.name,
                        "complexity": block.complexity,
                        "rank": rank,
                        "type": block.type,  # 'method' or 'function'
                    })

                # 模块级统计
                if blocks:
                    total_cc = sum(b.complexity for b in blocks)
                    avg_cc = total_cc / len(blocks) if blocks else 0
                    max_cc = max(b.complexity for b in blocks)
                    module_results.append({
                        "file": filepath,
                        "total_complexity": total_cc,
                        "avg_complexity": round(avg_cc, 1),
                        "max_complexity": max_cc,
                        "function_count": len(blocks),
                        "high_cc_count": len(high_cc),
                    })

            except SyntaxError:
                # 跳过有语法错误的文件
                continue
            except Exception as e:
                print(f"[警告] 分析 {filepath} 时出错: {e}", file=sys.stderr)
                continue

    # 按复杂度降序排序
    cc_results.sort(key=lambda x: -x["complexity"])
    module_results.sort(key=lambda x: -x["max_complexity"])

    return {"cc_results": cc_results, "module_results": module_results}


def format_vulture_report(results: list[dict]) -> str:
    """格式化 vulture 扫描结果为 Markdown 报告"""
    lines = []
    lines.append("## 未使用代码（vulture）\n")

    if not results:
        lines.append("✅ 未检测到明显未使用的代码。\n")
        return "\n".join(lines)

    lines.append(f"共检测到 **{len(results)}** 处未使用代码：\n")

    # 按类型分组
    by_type = {}
    for item in results:
        t = item["type"]
        by_type.setdefault(t, []).append(item)

    type_names = {
        "function": "未使用函数",
        "class": "未使用类",
        "variable": "未使用变量",
        "import": "未使用导入",
        "attribute": "未使用属性",
    }

    for typ, items in sorted(by_type.items()):
        name = type_names.get(typ, typ)
        lines.append(f"### {name}（{len(items)} 处）\n")
        lines.append("| 文件 | 行号 | 名称 | 置信度 |")
        lines.append("|------|------|------|--------|")
        for item in items:
            # 显示相对路径
            rel_path = os.path.relpath(item["file"], PROJECT_ROOT)
            conf = f"{item['confidence']}%"
            lines.append(f"| `{rel_path}` | {item['line']} | `{item['name']}` | {conf} |")
        lines.append("")

    return "\n".join(lines)


def format_radon_report(radon_data: dict, cc_threshold: int) -> str:
    """格式化 radon 分析结果为 Markdown 报告"""
    lines = []
    cc_results = radon_data["cc_results"]
    module_results = radon_data["module_results"]

    lines.append("## 圈复杂度分析（radon）\n")
    lines.append(f"复杂度阈值：**{cc_threshold}**（超过此值的函数被标记）\n")

    # 高复杂度函数
    if cc_results:
        lines.append(f"### 高复杂度函数（{len(cc_results)} 个）\n")
        lines.append("| 文件 | 行号 | 函数名 | 类型 | 复杂度 | 等级 |")
        lines.append("|------|------|--------|------|--------|------|")
        for item in cc_results:
            rel_path = os.path.relpath(item["file"], PROJECT_ROOT)
            lines.append(
                f"| `{rel_path}` | {item['line']} | `{item['name']}` "
                f"| {item['type']} | **{item['complexity']}** | {item['rank']} |"
            )
        lines.append("")
    else:
        lines.append(f"✅ 没有函数超过复杂度阈值 {cc_threshold}。\n")

    # 模块级统计（只显示有复杂度的模块，按最大复杂度排序，取前 20）
    top_modules = [m for m in module_results if m["max_complexity"] >= 5][:20]
    if top_modules:
        lines.append("### 模块复杂度概览（Top 20）\n")
        lines.append("| 文件 | 函数数 | 总复杂度 | 平均复杂度 | 最大复杂度 | 高复杂度函数数 |")
        lines.append("|------|--------|----------|------------|------------|----------------|")
        for m in top_modules:
            rel_path = os.path.relpath(m["file"], PROJECT_ROOT)
            lines.append(
                f"| `{rel_path}` | {m['function_count']} "
                f"| {m['total_complexity']} | {m['avg_complexity']} "
                f"| **{m['max_complexity']}** | {m['high_cc_count']} |"
            )
        lines.append("")

    return "\n".join(lines)


def generate_report(
    vulture_results: list[dict] | None,
    radon_data: dict | None,
    cc_threshold: int,
    elapsed: float,
) -> str:
    """生成完整的 Markdown 报告"""
    lines = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines.append("# 代码质量扫描报告\n")
    lines.append(f"- **扫描时间**：{now}")
    lines.append(f"- **扫描目录**：{', '.join(SCAN_DIRS)} + 根目录 .py 文件")
    lines.append(f"- **排除目录**：{', '.join(sorted(EXCLUDE_DIRS))}")
    lines.append(f"- **白名单文件**：`.vulture_whitelist`")
    lines.append(f"- **耗时**：{elapsed:.1f} 秒\n")
    lines.append("---\n")

    if vulture_results is not None:
        lines.append(format_vulture_report(vulture_results))
        lines.append("---\n")

    if radon_data is not None:
        lines.append(format_radon_report(radon_data, cc_threshold))
        lines.append("---\n")

    lines.append("## 建议\n")
    lines.append("1. **未使用代码**：逐项确认是否真的未使用，可能是动态调用/反射/框架注册")
    lines.append("2. **高复杂度函数**：考虑拆分为更小的函数，降低认知负担")
    lines.append("3. **白名单维护**：确认是误报的，添加到 `.vulture_whitelist`")
    lines.append("4. **本报告仅供人工审查参考**，不会自动删除任何代码\n")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="代码质量扫描 - 未使用代码检测 + 圈复杂度分析"
    )
    parser.add_argument(
        "--vulture", action="store_true",
        help="仅运行 vulture 扫描（未使用代码）"
    )
    parser.add_argument(
        "--radon", action="store_true",
        help="仅运行 radon 扫描（圈复杂度）"
    )
    parser.add_argument(
        "--threshold", type=int, default=0,
        help=f"vulture 最小置信度阈值 (0-100)，默认 0"
    )
    parser.add_argument(
        "--cc-threshold", type=int, default=DEFAULT_CC_THRESHOLD,
        help=f"圈复杂度阈值，默认 {DEFAULT_CC_THRESHOLD}"
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="输出报告到指定文件（Markdown 格式），默认输出到终端"
    )
    args = parser.parse_args()

    # 如果两个都没指定，就都运行
    run_vulture = args.vulture or not args.radon
    run_radon = args.radon or not args.vulture

    print(f"[信息] 开始代码质量扫描...")
    print(f"[信息] 项目根目录: {PROJECT_ROOT}")
    start_time = time.time()

    vulture_results = None
    radon_data = None

    if run_vulture:
        print(f"[信息] 运行 vulture 扫描（置信度阈值: {args.threshold}%）...")
        vulture_results = run_vulture_scan(threshold=args.threshold)
        print(f"[信息] vulture 完成，检测到 {len(vulture_results)} 处未使用代码")

    if run_radon:
        print(f"[信息] 运行 radon 圈复杂度分析（阈值: {args.cc_threshold}）...")
        radon_data = run_radon_scan(cc_threshold=args.cc_threshold)
        print(f"[信息] radon 完成，检测到 {len(radon_data['cc_results'])} 个高复杂度函数")

    elapsed = time.time() - start_time

    # 生成报告
    report = generate_report(vulture_results, radon_data, args.cc_threshold, elapsed)

    # 输出
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = PROJECT_ROOT / output_path
        output_path.write_text(report, encoding="utf-8")
        print(f"[信息] 报告已保存到: {output_path}")
    else:
        print("\n" + "=" * 60)
        print(report)

    print(f"\n[完成] 扫描耗时 {elapsed:.1f} 秒")


if __name__ == "__main__":
    main()
