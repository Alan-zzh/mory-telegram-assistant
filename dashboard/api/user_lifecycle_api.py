# -*- coding: utf-8 -*-
"""
Dashboard API - 用户生命周期分布统计

提供端点：
  GET /api/user-lifecycle/distribution - 返回各阶段用户数量
"""
from flask import Blueprint, jsonify
from dashboard.helpers import login_required, get_db
from core.logging_util import get_logger

logger = get_logger(__name__)

user_lifecycle_bp = Blueprint('user_lifecycle', __name__, url_prefix='/api/user-lifecycle')


@user_lifecycle_bp.route('/distribution')
@login_required
def get_distribution():
    """获取用户生命周期阶段分布
    ---
    tags:
      - 用户生命周期
    summary: 获取各生命周期阶段的用户数量分布
    description: |
      返回 New / Active / Silent / Churning / Lost 五个阶段的
      用户数量及总数。如果 lifecycle_stage 列尚未同步，
      返回全零数据并提示等待定时任务执行。
    responses:
      200:
        description: 成功返回分布数据
        schema:
          type: object
          properties:
            code:
              type: integer
              example: 200
            data:
              type: object
              properties:
                New:
                  type: integer
                  description: 新用户数
                Active:
                  type: integer
                  description: 活跃用户数
                Silent:
                  type: integer
                  description: 沉默用户数
                Churning:
                  type: integer
                  description: 流失风险用户数
                Lost:
                  type: integer
                  description: 已流失用户数
                total:
                  type: integer
                  description: 用户总数
            msg:
              type: string
              example: "success"
      500:
        description: 获取失败
    """
    try:
        conn = get_db()
        
        # 检查 lifecycle_stage 列是否存在
        cursor = conn.execute("PRAGMA table_info(user_profiles)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'lifecycle_stage' not in columns:
            # 列不存在，返回空数据
            return jsonify({
                "code": 200,
                "data": {
                    "New": 0,
                    "Active": 0,
                    "Silent": 0,
                    "Churning": 0,
                    "Lost": 0,
                    "total": 0
                },
                "msg": "lifecycle_stage 列尚未同步，等待定时任务执行"
            })
        
        # 查询各阶段用户数量
        cursor = conn.execute("""
            SELECT 
                lifecycle_stage,
                COUNT(*) as count
            FROM user_profiles
            GROUP BY lifecycle_stage
        """)
        
        distribution = {
            "New": 0,
            "Active": 0,
            "Silent": 0,
            "Churning": 0,
            "Lost": 0
        }
        
        for row in cursor.fetchall():
            stage = row[0]
            count = row[1]
            if stage in distribution:
                distribution[stage] = count
        
        distribution["total"] = sum(distribution.values())
        
        return jsonify({
            "code": 200,
            "data": distribution,
            "msg": "success"
        })
    except Exception as e:
        logger.exception("[user_lifecycle] 获取分布失败")
        return jsonify({
            "code": 500,
            "data": None,
            "msg": "内部错误，请联系管理员"
        }), 500
