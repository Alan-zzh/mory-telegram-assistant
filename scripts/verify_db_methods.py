#!/usr/bin/env python3
"""v5.31.1 第三层防御：部署前 DB 方法注册验证脚本。"""

import inspect
import os
import sys

try:
    # Windows 父控制台可能仍是 GBK/ASCII；验证脚本必须稳定输出中文状态。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import DB


def verify():
    """静态扫描 Repo 类方法并比对 _REPO_METHOD_MAP（不需要实例化 DB）。"""
    from core.db_repos import (
        ABTestRepo,
        ConfigRepo,
        ConversationContextRepo,
        AdEnforcementRepo,
        GroupRepo,
        PointsRepo,
        QuestionRepo,
        RelayRepo,
        ReplyEvolutionRepo,
        SalesRepo,
        SocialRepo,
        TaskExecHistoryRepo,
        TrackingRepo,
        UserRepo,
    )

    repo_class_map = [
        (UserRepo, "users", "users"),
        (GroupRepo, "groups", "groups"),
        (PointsRepo, "points", "points"),
        (TrackingRepo, "tracking", "tracking"),
        (ConfigRepo, "config", "config"),
        (SocialRepo, "social", "social"),
        (QuestionRepo, "questions", "questions"),
        (RelayRepo, "relay", "relay"),
        (ABTestRepo, "ab_test", "ab_test"),
        (SalesRepo, "sales", "sales"),
        (ReplyEvolutionRepo, "reply_evolution", "reply_evolution"),
        (ConversationContextRepo, "conversation_context", "conversation_context"),
        (TaskExecHistoryRepo, "task_exec_history", "task_exec_history"),
        (AdEnforcementRepo, "ad_enforcement", "ad_enforcement"),
    ]
    internal_methods = {"conn", "lock", "db_file"}
    missing = []
    orphaned = []

    for repo_cls, attr_name, map_key in repo_class_map:
        for name, _method in inspect.getmembers(repo_cls, predicate=inspect.isfunction):
            if name.startswith("_") or name in internal_methods:
                continue
            mapped = DB._REPO_METHOD_MAP.get(name)
            if mapped is None:
                missing.append((attr_name, name, map_key))
            elif mapped != map_key:
                missing.append((attr_name, name, f"mapped to '{mapped}' should be '{map_key}'"))

    repo_map_keys = {map_key for _, _, map_key in repo_class_map}
    for method_name, repo_key in DB._REPO_METHOD_MAP.items():
        if repo_key not in repo_map_keys:
            orphaned.append((method_name, f"repo '{repo_key}' not found"))
            continue
        repo_cls = next((cls for cls, _, key in repo_class_map if key == repo_key), None)
        if repo_cls is not None and not hasattr(repo_cls, method_name):
            orphaned.append((method_name, f"registered to '{repo_key}' but method does not exist"))

    return missing, orphaned


def main():
    fix_mode = "--fix" in sys.argv
    missing, orphaned = verify()

    if not missing and not orphaned:
        total = len(DB._REPO_METHOD_MAP)
        print(f"✅ DB 方法注册验证通过：{total} 个委托方法，无缺失、无孤儿")
        return 0

    print("=" * 70)
    if missing:
        print(f"❌ {len(missing)} 个 Repo 方法未在 _REPO_METHOD_MAP 注册：")
        for attr, name, expected in missing:
            print(f"   {attr}.{name}() → should map to '{expected}'")
        print()
        if fix_mode:
            print("自动生成注册代码（复制到 _REPO_METHOD_MAP 中）：")
            from collections import defaultdict

            by_repo = defaultdict(list)
            for attr, name, expected in missing:
                repo_key = (
                    expected
                    if not (isinstance(expected, str) and expected.startswith("mapped"))
                    else attr
                )
                by_repo[repo_key].append(f"'{name}': '{repo_key}'")
            for repo_key, entries in sorted(by_repo.items()):
                print(f"\n        # [AUTO-FIX] {repo_key}_repo 新增方法")
                for entry in entries:
                    print(f"        {entry},")
            print()
    if orphaned:
        print(f"⚠️ {len(orphaned)} 个 _REPO_METHOD_MAP 注册项在 Repo 中不存在：")
        for name, reason in orphaned:
            print(f"   {name}() → {reason}")
    print("=" * 70)
    return 1


if __name__ == "__main__":
    sys.exit(main())
