# -*- coding: utf-8 -*-
"""转化漏斗可视化 API（v5.26.0）

提供端点：
  GET /api/analytics/funnel - 返回 7 天转化漏斗数据
  GET /api/analytics/funnel/trend - 返回转化趋势（按天）
"""
import time
from datetime import datetime, timedelta, timezone
from flask import Blueprint, jsonify, request
from dashboard.helpers import login_required, get_db

# 【Loop 16】CST 时区，避免 VPS(UTC) 下漏斗显示日期错位 8 小时
_CST = timezone(timedelta(hours=8))

funnel_bp = Blueprint('funnel', __name__, url_prefix='/api/analytics')


@funnel_bp.route('/funnel')
@login_required
def get_funnel():
    """获取转化漏斗数据（7 天）

    返回格式：
    {
        "code": 200,
        "data": {
            "stages": [
                {"name": "touched", "label": "接触", "count": 100, "rate": 100.0},
                {"name": "interested", "label": "感兴趣", "count": 60, "rate": 60.0},
                {"name": "carted", "label": "加购", "count": 30, "rate": 50.0},
                {"name": "converted", "label": "转化", "count": 15, "rate": 50.0}
            ],
            "period": {"days": 7, "start": "2026-06-11", "end": "2026-06-18"}
        },
        "msg": "success"
    }
    """
    try:
        days = min(int(request.args.get('days', 7)), 90)
        cutoff = int(time.time()) - days * 86400
        conn = get_db()

        # 从 funnel_state 表聚合各阶段用户数
        cursor = conn.execute("""
            SELECT state, COUNT(*) as count
            FROM funnel_state
            WHERE state_ts > ?
            GROUP BY state
        """, (cutoff,))

        stage_counts = {}
        for row in cursor.fetchall():
            stage_counts[row[0]] = row[1]

        # 定义漏斗阶段顺序
        stages_def = [
            ('touched', '接触'),
            ('interested', '感兴趣'),
            ('carted', '加购'),
            ('converted', '转化')
        ]

        stages = []
        prev_count = None
        for name, label in stages_def:
            count = stage_counts.get(name, 0)
            # 计算转化率：相对于上一阶段
            if prev_count is None:
                rate = 100.0 if count > 0 else 0.0
            else:
                rate = round(count / prev_count * 100, 2) if prev_count > 0 else 0.0

            stages.append({
                'name': name,
                'label': label,
                'count': count,
                'rate': rate
            })
            prev_count = count

        # 计算时间范围
        end_date = datetime.now(_CST)
        start_date = end_date - timedelta(days=days)

        return jsonify({
            'code': 200,
            'data': {
                'stages': stages,
                'period': {
                    'days': days,
                    'start': start_date.strftime('%Y-%m-%d'),
                    'end': end_date.strftime('%Y-%m-%d')
                }
            },
            'msg': 'success'
        })
    except Exception as e:
        return jsonify({
            'code': 500,
            'data': None,
            'msg': f'获取漏斗数据失败: {str(e)}'
        }), 500


@funnel_bp.route('/funnel/trend')
@login_required
def get_funnel_trend():
    """获取转化趋势（按天）

    返回格式：
    {
        "code": 200,
        "data": {
            "dates": ["2026-06-11", "2026-06-12", ...],
            "series": {
                "touched": [10, 15, 12, ...],
                "interested": [6, 9, 8, ...],
                "carted": [3, 5, 4, ...],
                "converted": [1, 2, 2, ...]
            }
        },
        "msg": "success"
    }
    """
    try:
        days = min(int(request.args.get('days', 7)), 90)
        cutoff = int(time.time()) - days * 86400
        conn = get_db()

        # 按天聚合各阶段新增用户数（使用 state_ts 作为时间戳）
        # SQLite 日期格式化：date(ts, 'unixepoch') 返回 YYYY-MM-DD
        cursor = conn.execute("""
            SELECT
                date(state_ts, 'unixepoch') as dt,
                state,
                COUNT(*) as count
            FROM funnel_state
            WHERE state_ts > ?
            GROUP BY dt, state
            ORDER BY dt
        """, (cutoff,))

        # 构建日期到各阶段计数的映射
        trend_map = {}
        for row in cursor.fetchall():
            dt, state, count = row[0], row[1], row[2]
            if dt not in trend_map:
                trend_map[dt] = {
                    'touched': 0,
                    'interested': 0,
                    'carted': 0,
                    'converted': 0
                }
            if state in trend_map[dt]:
                trend_map[dt][state] = count

        # 转换为前端需要的格式
        dates = sorted(trend_map.keys())
        series = {
            'touched': [],
            'interested': [],
            'carted': [],
            'converted': []
        }

        for dt in dates:
            data = trend_map[dt]
            series['touched'].append(data['touched'])
            series['interested'].append(data['interested'])
            series['carted'].append(data['carted'])
            series['converted'].append(data['converted'])

        return jsonify({
            'code': 200,
            'data': {
                'dates': dates,
                'series': series
            },
            'msg': 'success'
        })
    except Exception as e:
        return jsonify({
            'code': 500,
            'data': None,
            'msg': f'获取趋势数据失败: {str(e)}'
        }), 500
