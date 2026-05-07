# -*- coding: utf-8 -*-
"""
版本管理文件

统一管理Mory小助理项目的版本号，确保所有模块版本一致。
"""

# 项目版本号（语义化版本）
VERSION = "v4.5.33"

CONFIG_VERSION = "4.5.33"

VERSION_HISTORY = [
    "v4.5.33: 修复时区处理漏洞(数据库+admin_cmds统一_CST)+线程池资源泄漏(全局_append_pool)+HTML注入安全漏洞(html.escape)+频道配置兼容性+日报数据解构修复+数据库级任务抢占(reactivate/cart_recovery/leak)",
    "v4.5.32: 彻底修复多进程连发(start.sh强力清理SIGKILL+等待退出+防残留)",
    "v4.5.31: 彻底修复连发问题(task_log添加UNIQUE约束+INSERT OR IGNORE+_try_claim_task全局替换+coalesce=True+misfire_grace_time=60)",
    "v4.5.30: 彻底修复连发问题(misfire_grace_time=1秒，错过执行窗口绝不补发)",
    "v4.5.29: 修复早安/新闻连发(_try_claim_task原子锁+APScheduler max_instances=1)+新增AI广告检测(check_ad_content删除+永久禁言+通知管理员)",
    "v4.5.28: 日报群成员数直接调API+入群名字检测虚拟币/搬砖等关键词自动永久禁言(AUTO_MUTE_NAMES配置化)",
    "v4.5.27: 日报数据全0修复(_send_and_track加track_channel_message+_job_channel_views修复None判断+加锁+日报增加活跃用户/Bot消息数/互动率/群成员数+database新增4个查询方法)",
    "v4.5.26: S-AI-01 ContextLogger没有addFilter方法，改为logger.logger.addFilter()",
    "v4.5.25: S-AT-01 fallback路径线程泄漏彻底修复(移除长休眠Timer+跳过期删除依赖孤儿清理)",
    "v4.5.24: 板块C二次审查修复(fallback路径Timer替代长休眠线程+burn_orphan加锁+Phase2每小时一次+塔罗缓存入口主动清空+通知缓存过期清理+旧版循环全任务隔离)",
    "v4.5.22: auto_tasks二次审查修复(fallback路径Timer替代长休眠线程+burn_orphan加锁+Phase2每小时一次+塔罗缓存入口主动清空+通知缓存过期清理+旧版循环全任务隔离)",
    "v4.5.21: Dashboard二次审查修复(变量名NameError+forbidden_keys精确匹配+速率限制每次清理+VPS状态5分钟缓存)",
    "v4.5.19: Dashboard安全漏洞7项修复(SQL注入/XSS/登录持久化/速率限制/DB连接/敏感过滤/SSH策略)",
    "v4.5.18: auto_tasks线程泄漏修复(24h休眠线程→APScheduler)+新闻缓存竞态加锁+重试线程改APScheduler+Phase2降频+塔罗缓存简化+重复导入清理+旧版循环超时保护",
    "v4.5.17: M-DU-01修复shell注入风险(sync_env_api_key改SFTP)+L-DU-01修复VPS配置下载失败静默忽略+Dashboard安全审计修复",
    "v4.5.16: Dashboard安全修复(hmac密码比较)+图表真实数据绑定+删除死代码",
    "v4.5.15: Telegram/网页自然语言配置接通+特定回复可直改+部署前先拉线上投喂配置",
    "v4.5.14: 修复SPECIAL_AUTO_REPLIES部署白名单遗漏+服务器配置同步补齐",
    "v4.5.13: 老板/boss/Mory称呼联动+特定词自动回复配置化+AI润色触发",
    "v4.5.12: 早午晚安提示词强化随机性+隐晦高情商转化牵引",
    "v4.5.11: 新闻播报主流程合并去重+TrendRadar改为优先新闻源+问候文案去广告腔",
    "v4.5.10: 全模态模型优先用于文本聊天+熔断日志按实际调用模型对齐",
    "v4.5.9: 模型切换智能化加固+独立路由去硬编码密钥+账号冷却策略修复",
    "v4.5.8: 修复Windows启动脚本乱码风险+Dashboard临时密钥启动+sync_vps导入误部署风险",
    "v4.5.4: 晚间新闻零token+7新闻源+故障通知",
    "v4.5.3: 修复自动回复bug+阅后即焚两阶段清理(30分钟窗口+用户删消息检测)",
    "v4.5.2: TrendRadar早中晚新闻播报+去重机制",
    "v4.5.0: 全面整理：79个冗余文件清理+文档整合+版本号同步",
    "v4.4.2: 修复任务队列长度限制，防止内存泄漏",
    "v4.4.1: 优化日志记录，增加详细的错误信息",
    "v4.4.0: 新增智能路由功能，支持多模态模型自动匹配",
    "v4.3.8: 修复morning/afternoon/evening模板seed_hint替换问题",
    "v4.3.7: 优化Omni池降级逻辑，提高稳定性",
    "v4.3.6: 修复新闻模式真实数据注入问题",
    "v4.3.5: 增加模型池状态信息获取功能",
    "v4.3.4: 优化令牌桶限流算法，提高并发处理能力",
    "v4.3.3: 修复全局请求超时保护，增加任务队列守卫",
    "v4.3.2: 修复多项稳定性问题，增强系统鲁棒性",
    "v4.3.1: 修复API_KEY读取逻辑，兼容旧DASHSCOPE_KEY",
    "v4.3.0: 新增AI识图分析功能，支持图片理解",
    "v4.2.3: 记录频道/群消息用于追踪浏览量",
    "v4.2.2: 优化用户画像标签提取逻辑",
    "v4.2.1: 修复连续对话追踪的线程安全问题",
    "v4.2.0: 新增连续对话绿茶风反问功能",
    "v4.1.0: 架构升级，新增BaseMiddleware全局底层嗅探器",
    "v4.0.0: 架构级重构，废除forward_message探测法",
]
