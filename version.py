# -*- coding: utf-8 -*-
"""
版本管理文件

统一管理Mory小助理项目的版本号，确保所有模块版本一致。
"""

# 项目版本号（语义化版本）
VERSION = "v5.16.3"

CONFIG_VERSION = "5.16.3"

VERSION_HISTORY = [
    "v5.16.3: [Codex] 工作区脏改动收敛 - 合并模块化拆分(core/db_repos/core/handlers/dashboard/api/modules全量分层)+config.json退出Git跟踪并保留本地运行文件+.gitignore补backup/logs/config.json+清理旧debug脚本/旧universal_ai_router目录/start.sh/deploy.sh/windows_helper+补MEMBER_SCAN_METHOD和技术文档索引+验证54条单测和全量py_compile通过",
    "v5.16.2: [Codex] 广告治理策略纠正 - 广告账号不踢人，统一永久禁言+删除消息+global_blacklist+blacklist+message_snapshots历史清理；新增modules/ad_enforcement.py统一入口；emoji面具复用广告主正则；头像OCR补充看我简/主页/钱包/打底/进群了解；早午晚问候时间和开关配置化；商业搭讪落库冷却+分阶段fallback；文档纠正旧踢人规则",
    "v5.16.1: 看我简介变体+bio核心骗术模式补充 - USERNAME_PATTERNS扩展字符集(个/jie/接/界/衔+拼音jianjie/jian-jie+无前缀看X简X)+BIO_PATTERNS补充一天保X万/数字+打底/带X钱包/想做兄弟/进群找了解/付出保X+31条单测全通过",
    "v5.16.0: 未实现功能汇总全部执行 - Dashboard gunicorn+gevent WSGI部署 + mory-assistant.service EnvironmentFile + logs/config目录同步 + 备份保留策略(保留最近2个) + 部署验证自动化(4步systemctl/health/log/config) + 多Bot Dashboard独立(DASHBOARD_MODE分区+media服务文件) + FAQ自动回复配置上线 + 暗病修复(Dashboard media模式自动建库+gunicorn apt安装+Windows stdout UTF-8+python3 -m gunicorn路径)",
    "v5.15.4: v5.15.3验收+18:36历史债收尾-VPS端5/5验证(systemctl双active+3文件MD5一致+message_snapshots表结构正确+代码含_job_startup_history_cleanup注册) +E2E 13/13(7命中+6不命中) +SSH凭据bug修复(scripts/ssh_helper.py ENV_PATH指向scripts/.env改为项目根) +方案B三种方式全失败(ad_suspicious_users 0/15条含917895208+deleted_messages 0+reply_tracking/broadcast_tracking 列不含uid/user_id) +降级方案A: Alan哥手动右键删一次+5篇文档同步",
    "v5.15.3: 打码/收款码/新项目广告漏检修复 - message_snapshots表落地(4索引+UNIQUE(chat_id,msg_id)+is_ad/deleted)+P1拦截5步升级(删+踢+同步+日志+mark_message_deleted)+message_dispatcher强制所有入分发消息入表+启动追溯job(APScheduler+legacy双轨)+uid=917895208已加blacklist+group_repo 3方法",
    "v5.14.2: 入群即检测三重广告信号 - member_handlers新增步骤2.5(ad_detector.detect跑名字+BIO+头像)+bio拉取容错+评分>=3立即踢出+评分2-3入可疑追踪表+50个历史积压可疑用户清理(其中含Yao/私信我/裸聊/套利/拍.唓等变体)",
    "v5.14.1: 广告变体字规避修复 - _normalize_ad_evasion()反规避规范化(全角数字/形近字/繁体→简体)+BIO_PATTERNS 14条新规则(刷礼物/私信/滴滴/1000U/一天干/有抖音)+E2E自检脚本verify_ad_detection_live.py+5条历史广告删除+用户8884907937封禁",
    "v5.14.0: 商业问题主动搭讪引导 - convert关键词扩展(6→50+词含订阅/月付/年付/视频/观看/解锁/购买/付费等)+P7.5主动搭讪层(默认关闭PROACTIVE_ENGAGE_CONFIG)+30分钟跨群冷却+数据库proactive_engage_log表+Dashboard /api/engage/{stats,recent,config} 4端点+convert模式跳过REPLY_CHANCE强制回复+视奸雷达P7扩展proactive_eligible标志位+模块拆分proactive_engage.py+engaged转化追踪",
    "v5.12.4: 孤儿消息真清理 - 30分钟窗口(86400→1800)+独立ORPHAN_CLEANUP_ENABLED开关(默认true,不依赖ENABLE_MESSAGE_DELETION)+proactive_engage改用track_bot_message(避免搭讪变孤儿)+force_orphan_cleanup.py批量清积压脚本(支持--dry-run/--limit/--window)+Dashboard /api/orphan/stats加orphan_30m_count+enable_orphan_cleanup字段+force-clean端点升级为立即清理+Dashboard /api/settings/orphan-cleanup读写端点+can_orphan_cleanup独立判断函数",
    "v5.13.0: 全面健康诊断与暗病修复：6个VPS运行时严重问题（开机自启+speech_stats Cursor+不活跃清理类型错误+fault_reporter缺失+conversions表缺失+last_active不更新）+8个代码严重问题（网络请求无超时+沉默失败11处+循环依赖确认+TOKEN泄露+无锁全局状态+N+1查询+漏注册DB方法确认+12个配置键缺失）+5个中等问题（Dashboard /api/health+API信息泄露22处+API Key脱敏+积分转账原子性+孤儿清理delete_tracked提前清除）+Dashboard health_api.py新建+config.json.example补全12键",
    "v5.12.3: 能力矩阵真实还原（SYSTEM_PROMPT 10维/3段对话轮次/4 PROMPT_TEMPLATES/25 MODE_ROUTING/9模型池/83 modules/95+ API/25 P级别/40任务/84表）+ 文档除断章取义（删除7模式/SPECIAL_AUTO_REPLIES/200行限制/未做话术）+ AGENTS.md F3/F4铁律修订 + README大重做",
    "v5.12.2: 业务核心目标重写（运营型商业 AI 转化机器人定位+6条业务红线）+ 详尽能力矩阵 docs/technical/capability-matrix.md 新建（182行：人设对话/商业闭环/群管80+/运营观察/消息分发 P0-P10）+ README 大重做（196→324 行：项目定位/5步转化流程/6大功能矩阵/完整文档索引）",
    "v5.12.1: 项目规则归一化(.agents→AGENTS.md大写显式+业务核心目标+历史文档优先原则+技术边界+5条核心教训+8条跨AI一致性铁律F1-F8)+根目录50+临时文件归档tests/_archive/+docs/technical子目录分类(kebab-case命名)+跨AI一致性铁律化",
    "v5.12.0: 孤儿消息实际清理（orphan_cleanup_log表+/api/orphan/stats端点+ENABLE_MESSAGE_DELETION关闭告警+verify_orphan_cleanup.py脚本）+8大类老坑规则化（.agents新增『反复出现的老坑与铁律』章节+docs/技术细节文档索引）+项目规则归一化（project_rules.md合并删除）",
    "v5.10.4: AI认知纠正文档：Bot API限制已有解决方案写入项目规则",
    "v5.10.3: VPS用户统一ubuntu(消除root/ubuntu双用户权限冲突)+.agents项目规则整合",
    "v5.10.2: 配置热重载(Dashboard→Bot 5秒同步)+VPS配置自动补齐+ANTI_CHANNEL_DEFAULT命名修复+ANTIFLOOD_CONFIG补充+SESSION_COOKIE_SECURE环境变量化",
    "v5.9.2: 遗留债务收尾：auto_tasks旧模式完全迁移(_can_run/_mark_done/_release_task归零)+message_dispatcher进一步拆分(1627→1286行)+AI回复逻辑独立(345行)+Dashboard systemd环境变量注入",
    "v5.9.1: 技术债务清偿：message_dispatcher拆分(2615→1627行)+TaskTransactionManager统一事务管理+_release_task从38→0+universal_ai_router清理+Dashboard systemd服务+6个重叠spec合并为2个",
    "v5.8.4: Pyrogram全量扫描5811人(95.7%覆盖)+封禁2广告号+HIGH_NAME级高分显示名封禁规则",
    "v5.8.3: 广告检测5规则漏洞修复+误报修正+全量扫描封禁11人",
    "v5.8.2: 消息发送者追踪+显示名广告检测+消息历史扫描",
    "v5.8.1: 两层组合直接封禁+全量扫描+成员追踪",
    "v5.8.0: 集成CAS/SPB反垃圾数据库+白名单+三层组合封禁",
    "v5.7.5: 用户资料(Bio)广告检测+短随机用户名检测+头像检测触发扩展",
    "v5.7.4: 零宽字符绕过修复+零宽占比可疑信号+谐音变体补全",
    "v5.7.3: 阅后即焚三层保障修复",
    "v5.7.2: L4追溯广告扫描：启动自动扫描+双模式+/scan_ads命令",
    "v5.7.1: 409 Conflict死循环修复",
    "v5.7.0: AI引擎全量修复 - user_profile/seed传入ask()+news_content参数修正+analyze_image/text_to_speech模型遍历+_slow_models线程安全+连续对话超时25秒+过期TTS/ASR模型清理+VPS空TOKEN修复",
    "v5.6.2: 广告检测彻底修复 - 三层广告漏检根治+强制删除+独立连续消息检测",
    "v5.5.0: 广告检测去重+密钥迁移+Dashboard缓存 - message_dispatcher P3.5逻辑统一调用security_handlers(消除130行重复) + config.json密钥优先从.env读取 + Dashboard read_config()5秒TTL缓存",
    "v5.4.0: 安全加固+性能优化+数据完整性修复 - SSH密钥验证+CSRF Token+死锁修复+DB锁优化+签到N+1修复+校准逻辑修正",
    "v5.1.0: 全栈自动审计与安全修复 - 220+问题审查+50+严重/高危问题自动修复+9个NameError致命Bug修复+架构统一+VPS部署验证",
    "v5.0.0: 全面审查优化与深度架构重构 - main.py拆分(3040→133行+15模块)+database.py拆分(2354→1004行+6Repo)+dashboard拆分(5385→57行+12模块)+废弃清理+安全修复+部署脚本补全",
    "v4.18.0: Dashboard全功能配置化 - 26+空壳页面补全+12后端API修复+4新页面+导航扩展",
    "v4.9.0: 根治并发重复播报 - _try_claim_and_lock原子抢占+_release_task失败释放",
    "v4.8.0: 人设精细化&对话拟人化 - 延迟系统+分层人设+自然语言调教+分段发送+AI参数微调",
    "v4.6.5: 色情引流暗号扩展(30+组合规则)+修复单字误判+pytz缺失修复+规则文档归档",
    "v4.5.0: 全面整理：79个冗余文件清理+文档整合+版本号同步+深度扫描18项致命/严重修复",
    "v4.4.0: 终极核查修复32项(3致命+4高危+16中+9低)",
    "v4.3.2: 致命修复27项+灾难恢复",
    "v4.0.0: 架构级重构，废除forward_message探测法",
]
