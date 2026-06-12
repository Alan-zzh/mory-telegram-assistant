# -*- coding: utf-8 -*-
"""数据库功能域仓库模块"""
from .user_repo import UserRepo
from .group_repo import GroupRepo
from .points_repo import PointsRepo
from .tracking_repo import TrackingRepo
from .config_repo import ConfigRepo
from .social_repo import SocialRepo
from .question_repo import QuestionRepo
from .relay_repo import RelayRepo

__all__ = ['UserRepo', 'GroupRepo', 'PointsRepo', 'TrackingRepo', 'ConfigRepo', 'SocialRepo', 'QuestionRepo', 'RelayRepo']
