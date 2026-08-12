# -*- coding: utf-8 -*-
"""v5.35.0 修复回归测试

覆盖本轮修复：
- P0-1 anti_raid 4 类断链 import 修复 + 模块级 check_raid 适配函数
- P0-2 36 模块 import 健康（断链 import 已全部修复）
- P0-3 36 模块 DB 表名访问（间接通过 import + DB 启动验证）
- P0-4 sales_repo order_no 同秒重复下单 UNIQUE 冲突修复

只做真实行为验证，不 mock 关键业务逻辑。
"""
import importlib
import os
import sys
import tempfile
import uuid

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


# ──────────────────── P0-1 anti_raid 修复回归 ────────────────────

class TestAntiRaidFix:
    """验证 anti_raid 4 类断链 import 修复 + 模块级适配函数"""

    def test_module_importable(self):
        """模块可正常 import（无 ImportError）"""
        from modules import anti_raid
        assert hasattr(anti_raid, 'check_raid')
        assert hasattr(anti_raid, 'get_status')
        assert hasattr(anti_raid, 'deactivate_raid')
        assert hasattr(anti_raid, 'AntiRaidModule')

    def test_check_raid_disabled_returns_false(self):
        """enabled=False 时 check_raid 直接返回 False，不触发任何动作"""
        from modules.anti_raid import check_raid

        class _FakeMsg:
            class _Chat:
                id = -100123
            chat = _Chat()
            new_chat_members = [type("U", (), {"id": 1})()]

        # config 显式 enabled=False
        result = check_raid(bot=None, m=_FakeMsg(), config={'ANTI_RAID_CONFIG': {'enabled': False}}, db=None)
        assert result is False

    def test_check_raid_no_config_returns_false(self):
        """config=None 也不抛异常，返回 False（防御性）"""
        from modules.anti_raid import check_raid

        class _FakeMsg:
            class _Chat:
                id = -100123
            chat = _Chat()
            new_chat_members = []

        result = check_raid(bot=None, m=_FakeMsg(), config=None, db=None)
        assert result is False

    def test_check_raid_enabled_with_no_db_returns_false(self):
        """enabled=True 但 db=None 时，无法统计入群记录，应返回 False 而非抛异常"""
        from modules.anti_raid import check_raid

        class _FakeMsg:
            class _Chat:
                id = -100456
            chat = _Chat()
            new_chat_members = [type("U", (), {"id": i})() for i in range(5)]

        # enabled=True + trigger=10，5 个新成员不足触发，且 db=None 不应抛异常
        result = check_raid(
            bot=None, m=_FakeMsg(),
            config={'ANTI_RAID_CONFIG': {'enabled': True, 'trigger_member_count': 10}},
            db=None
        )
        assert result is False

    def test_class_init_with_valid_config(self):
        """class AntiRaidModule 可正常初始化并查询状态"""
        from modules.anti_raid import AntiRaidModule

        m = AntiRaidModule(
            bot=None,
            config={'ANTI_RAID_CONFIG': {'enabled': False, 'trigger_member_count': 5}},
            db=None
        )
        status = m.get_status(chat_id=-100789)
        assert status['enabled'] is False
        assert status['trigger_member_count'] == 5
        assert status['active'] is False  # 无 db 时 is_raid_active 返回 False


# ──────────────────── P0-2 36 模块 import 健康 ────────────────────

# 修复的 36 模块清单
_FIXED_MODULES = [
    'ad_blocker', 'afool_member', 'auto_rules', 'bot_list', 'bot_settings',
    'bottom_button', 'channel_link', 'chat_points_cost', 'chat_settings',
    'config_template', 'content_archive', 'crypto_detector', 'entertainment_games',
    'force_channel', 'force_subscribe', 'group_commands', 'group_list', 'group_members',
    'group_message_push', 'group_migration', 'group_props', 'group_report',
    'group_safety_center', 'group_todo', 'image_manager', 'invite_link_manager',
    'join_settings', 'language_whitelist', 'message_library', 'new_member_probation',
    'punishment_center', 'random_drop', 'super_afool',
    'user_marking', 'valid_speak', 'word_cloud'
]


@pytest.mark.parametrize('module_name', _FIXED_MODULES)
def test_fixed_module_importable(module_name):
    """每个修复的模块都能正常 import（无 ImportError）"""
    m = importlib.import_module(f'modules.{module_name}')
    assert m is not None


def test_no_broken_import_pattern_remains():
    """扫描所有修复后的模块，确认 4 类断链 import 已全部清除"""
    broken_patterns = [
        'from core.settings import config',
        'from core.database import db_manager',
        'from core.telebot_compat import TelebotCompat',
        'from utils.logger import get_logger',
    ]
    import glob
    modules_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'modules')
    failures = []
    for py_file in glob.glob(os.path.join(modules_dir, '*.py')):
        with open(py_file, 'r', encoding='utf-8') as f:
            content = f.read()
        for pattern in broken_patterns:
            if pattern in content:
                failures.append(f'{os.path.basename(py_file)}: 仍含 "{pattern}"')
    assert not failures, '仍有断链 import 残留：\n' + '\n'.join(failures)


# ──────────────────── P0-4 sales_repo order_no 唯一性 ────────────────────

class TestSalesRepoOrderNoFix:
    """验证 sales_repo.create_order 的 order_no 唯一性修复"""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """临时 DB 实例（每个测试独立）"""
        from core.database import DB
        db_path = str(tmp_path / f'test_sales_{uuid.uuid4().hex[:8]}.db')
        db = DB(db_path)
        yield db
        # 清理
        try:
            db.close()
        except Exception:
            pass
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except (PermissionError, OSError):
                pass

    def test_create_order_same_second_same_uid_same_product(self, temp_db):
        """同秒同 uid 同 product_id 重复下单不应触发 UNIQUE 冲突"""
        db = temp_db
        db.sales.add_product('TEST_PRODUCT', 1.0, 'test_cat')
        # 直接查 products 表
        row = db.conn.execute('SELECT id FROM sales_products LIMIT 1').fetchone()
        pid = row[0]

        # 同秒重复下单 5 次
        order_ids = []
        for _ in range(5):
            oid = db.sales.create_order(uid=8888, product_id=pid, amount=1.0)
            order_ids.append(oid)

        # 5 个订单 id 全部不同
        assert len(set(order_ids)) == 5, f'订单 id 应唯一，实际: {order_ids}'

        # DB 中确实有 5 条订单
        cnt = db.conn.execute('SELECT COUNT(*) FROM sales_orders WHERE uid=8888').fetchone()[0]
        assert cnt == 5, f'应有 5 条订单，实际 {cnt}'

    def test_order_no_format_contains_uuid_suffix(self, temp_db):
        """order_no 应包含 uuid 后缀（长度 > 旧版 ORD{now}{uid}{pid}）"""
        db = temp_db
        db.sales.add_product('TEST', 1.0, 'cat')
        pid = db.conn.execute('SELECT id FROM sales_products LIMIT 1').fetchone()[0]
        db.sales.create_order(uid=9999, product_id=pid, amount=2.0)

        row = db.conn.execute(
            'SELECT order_no FROM sales_orders WHERE uid=9999 LIMIT 1'
        ).fetchone()
        order_no = row[0]
        # 旧版 ORD{10位时间戳}{4位uid}{1-3位pid} 约 17-19 字符
        # 新版加 8 位 uuid hex 后缀，应 >= 25 字符
        assert len(order_no) >= 25, f'order_no 长度不足，可能未含 uuid 后缀: {order_no}'
        assert order_no.startswith('ORD'), f'order_no 应以 ORD 开头: {order_no}'


# ──────────────────── P0-3 DB 表创建健康 ────────────────────

class TestDBTablesHealth:
    """验证 DB 启动后所有表（含 v5.35.0 新增 25 张）都创建成功"""

    @pytest.fixture
    def temp_db(self, tmp_path):
        from core.database import DB
        db_path = str(tmp_path / f'test_tables_{uuid.uuid4().hex[:8]}.db')
        db = DB(db_path)
        yield db
        try:
            db.close()
        except Exception:
            pass
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except (PermissionError, OSError):
                pass

    def test_all_v5350_new_tables_exist(self, temp_db):
        """v5.35.0 新增 25 张表全部存在"""
        expected_new_tables = [
            'global_ad_blacklist', 'member_info', 'bot_registry', 'user_points',
            'chat_points_usage', 'group_configs', 'config_templates',
            'config_template_applications', 'group_registry', 'member_actions',
            'groups', 'migration_records', 'user_props', 'image_records',
            'content_archive', 'invite_links', 'join_records', 'message_library',
            'probation_members', 'punishment_records', 'user_exp', 'user_items',
            'message_logs', 'premium_usage', 'user_marks'
        ]
        cur = temp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        actual_tables = {row[0] for row in cur.fetchall()}
        missing = [t for t in expected_new_tables if t not in actual_tables]
        assert not missing, f'缺失 v5.35.0 新表: {missing}'

    def test_total_tables_count_meets_metrics(self, temp_db):
        """总表数 >= 167（METRICS 基准）"""
        cur = temp_db.conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        count = cur.fetchone()[0]
        assert count >= 167, f'总表数 {count} < 167 (METRICS 基准)'

    def test_v5350_new_tables_allow_null_updated_at(self, temp_db):
        """v5.35.0 新表 updated_at 字段允许 NULL（修复 NOT NULL 缺字段 IntegrityError）"""
        # 抽检 5 个新表
        check_tables = ['chat_settings', 'join_settings', 'group_commands', 'bot_settings', 'afool_member']
        for table in check_tables:
            cur = temp_db.conn.execute(f"PRAGMA table_info({table})")
            cols = {row[1]: row[3] for row in cur.fetchall()}  # name -> notnull
            if 'updated_at' in cols:
                notnull = cols['updated_at']
                assert not notnull, f'{table}.updated_at 应允许 NULL（notnull=0），实际 notnull={notnull}'

    def test_insert_or_replace_without_updated_at_works(self, temp_db):
        """INSERT OR REPLACE 不带 updated_at 字段不应触发 IntegrityError"""
        # chat_settings 表是 v5.35.0 新表，updated_at 允许 NULL
        temp_db.conn.execute(
            "INSERT OR REPLACE INTO chat_settings (chat_id, data) VALUES (?, ?)",
            (-100999, '{"k":"v"}')
        )
        temp_db.conn.commit()
        row = temp_db.conn.execute(
            "SELECT chat_id, data FROM chat_settings WHERE chat_id=?",
            (-100999,)
        ).fetchone()
        assert row is not None
        assert row[0] == -100999


# ──────────────────── P0-5 version 一致性 ────────────────────

class TestVersionConsistency:
    """验证 version.py 与 VERSION.md 一致"""

    def test_version_py_matches_version_md(self):
        from version import VERSION
        version_md_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'VERSION.md'
        )
        with open(version_md_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # VERSION.md 应包含 version.py 的 VERSION 值
        assert VERSION in content, f'VERSION.md 不含 {VERSION}：\n{content}'

    def test_version_is_v5350(self):
        from version import VERSION
        # v5.35.3: 二轮审查修复；放宽断言为 >= v5.35.0（避免每次 bump 都要改测试）
        major, minor, patch = VERSION.lstrip('v').split('.')
        assert (int(major), int(minor), int(patch)) >= (5, 35, 0), f'当前版本应 >= v5.35.0，实际 {VERSION}'
