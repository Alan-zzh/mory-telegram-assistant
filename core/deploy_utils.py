"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/deploy_utils.py  ·  安全部署工具库                                    ║
║                                                                            ║
║  所有部署脚本必须使用此模块，确保：                                          ║
║  1. VPS上的敏感字段（TOKEN/API_KEY等）永远不会被本地值覆盖                  ║
║  2. config.json 上传前自动合并，只更新业务字段                              ║
║  3. 部署前自动备份VPS配置                                                  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import json, logging, os, posixpath, re, shlex, tempfile, time, uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("deploy_utils")


def filter_dashboard_teardown_noise(log_text: str) -> str:
    """只移除已确认的 logging/gevent 解释器退出栈，保留其他异常。"""
    lines = log_text.splitlines(keepends=True)
    kept = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if "Exception ignored in: <function _removeHandlerRef" not in line:
            kept.append(line)
            index += 1
            continue

        end = index
        while end < min(index + 16, len(lines)):
            if "RuntimeError: greenlet is being finalized" in lines[end]:
                break
            end += 1
        if end >= len(lines) or "RuntimeError: greenlet is being finalized" not in lines[end]:
            kept.append(line)
            index += 1
            continue

        block = "".join(lines[index:end + 1])
        exact_teardown = all(anchor in block for anchor in (
            "logging/__init__.py",
            "_removeHandlerRef",
            "_acquireLock",
            "gevent/thread.py",
            "get_ident",
            "greenlet is being finalized",
        ))
        if exact_teardown:
            index = end + 1
            continue
        kept.append(line)
        index += 1
    return "".join(kept)


_SCHEDULER_RECONCILE_BEGIN_RE = re.compile(
    r"SCHEDULER_RECONCILE_BEGIN mode=(?P<mode>startup|reload) generation=(?P<generation>[0-9]+)"
)
_SCHEDULER_RECONCILE_OK_RE = re.compile(
    r"SCHEDULER_RECONCILE_OK mode=(?P<mode>startup|reload) "
    r"generation=(?P<generation>[0-9]+) managed_jobs=(?P<managed_jobs>[0-9]+) "
    r"scene_triggers=reconciled dynamic_jobs=not_observed"
)


def _authenticated_scheduler_event(record: object) -> tuple[str, object] | None:
    """只接受本项目结构化日志中经过来源认证的调度事件。"""
    if not isinstance(record, dict):
        return None
    logger_name = record.get("logger")
    function = record.get("function")
    level = record.get("level")
    message = record.get("message")
    if not isinstance(message, str):
        return None

    if (
        logger_name == "tasks.task_scheduler"
        and function == "begin_scheduler_reconciliation"
        and level == "INFO"
    ):
        match = _SCHEDULER_RECONCILE_BEGIN_RE.fullmatch(message)
        if match:
            return "begin", (
                match.group("mode"),
                int(match.group("generation")),
            )

    if (
        logger_name == "tasks.task_scheduler"
        and function == "complete_scheduler_reconciliation"
        and level == "INFO"
    ):
        match = _SCHEDULER_RECONCILE_OK_RE.fullmatch(message)
        if match:
            return "complete", (
                match.group("mode"),
                int(match.group("generation")),
                int(match.group("managed_jobs")),
            )

    if (
        logger_name == "tasks.task_scheduler"
        and function == "_register_tasks"
        and level == "ERROR"
    ):
        return "failure", "task_registration_failed"
    if (
        logger_name == "modules.triggers.base"
        and function == "refresh_trigger_jobs"
        and level == "ERROR"
    ):
        return "failure", "scene_trigger_refresh_failed"
    if (
        logger_name == "bot_initializer"
        and function == "_apply_reloaded_config"
        and level == "CRITICAL"
    ):
        return "failure", "scheduler_rollback_failed"
    return None


def scheduler_registry_receipt_from_logs(log_text: str) -> tuple[int, str]:
    """从 ``journalctl -o cat`` JSON 日志生成来源认证的当前调度回执。"""
    events: list[tuple[int, str, object]] = []
    for index, line in enumerate(log_text.splitlines()):
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        event = _authenticated_scheduler_event(record)
        if event is not None:
            events.append((index, event[0], event[1]))

    begins = [event for event in events if event[1] == "begin"]
    completions = [event for event in events if event[1] == "complete"]
    if not completions:
        if begins:
            mode, generation = begins[-1][2]
            return (
                1,
                "SCHEDULER_RECONCILIATION_INCOMPLETE "
                f"mode={mode} generation={generation}",
            )
        return 2, "SCHEDULER_RECONCILIATION_RECEIPT_MISSING"

    complete_index, _, complete_payload = completions[-1]
    complete_mode, complete_generation, managed_jobs = complete_payload
    matching_begin = next(
        (
            event
            for event in reversed(begins)
            if event[0] < complete_index
            and event[2] == (complete_mode, complete_generation)
        ),
        None,
    )
    if matching_begin is None:
        return 2, "SCHEDULER_RECONCILIATION_BEGIN_MISSING"

    if begins and begins[-1][0] > complete_index:
        mode, generation = begins[-1][2]
        return (
            1,
            "SCHEDULER_RECONCILIATION_INCOMPLETE "
            f"mode={mode} generation={generation}",
        )

    reasons = sorted(
        {
            str(payload)
            for index, event_type, payload in events
            if index > complete_index and event_type == "failure"
        }
    )
    if reasons:
        return 1, "SCHEDULER_REGISTRY_UNHEALTHY reasons=" + ",".join(reasons)

    return (
        0,
        "SCHEDULER_REGISTRY_OK "
        "coverage=managed_jobs:authenticated_reconcile_receipt "
        "scene_triggers:authenticated_reconcile_receipt "
        "dynamic_jobs:not_observed direct_registry:false "
        f"managed_jobs={managed_jobs}",
    )

PROTECTED_FIELDS = [
    "TOKEN", "API_KEY", "API_KEYS", "ADMIN_ID", "GROUP_ID",
    "DASHBOARD_SECRET", "DASHBOARD_PASSWORD",
    "CHANNEL_IDS", "BASE_URL",
]

MERGE_FIELDS = [
    "MODEL_COSTS", "MODEL_POOLS", "MODE_ROUTING",
    "SYSTEM_PROMPT", "BASE_PERSONA", "PROMPT_TEMPLATES",
    "SPAM_LIMIT", "IMAGE_POOL", "LOG_LEVEL",
    "BOT_NAME", "REPLY_CHANCE", "COST_STRATEGY",
    "BANNED_WORDS", "HATE_KEYWORDS", "IGNORE_BOTS",
    "KNOWLEDGE", "PHOTO_KEYWORDS", "PRICE_LIST",
    "SPECIAL_AUTO_REPLIES",
    "PUZZLE_WORD", "SLANG_DICT",
    "AD_RULES", "AD_DETECT_CONFIG",
    "CHECKIN_CONFIG",
    "ENABLE_MESSAGE_DELETION",
    "_CONFIG_VERSION", "_CONFIG_UPDATED", "_SAFETY_NOTE",
]

try:
    from modules.natural_cmd import ALL_CONFIGS as _NATURAL_ALL_CONFIGS
    _natural_keys = set(_NATURAL_ALL_CONFIGS.keys())
except Exception as e:
    logger.debug(f"natural_cmd导入失败，RUNTIME_SYNC_FIELDS默认空集（非致命）：{e}")
    _natural_keys = set()

_MERGE_SET = set(MERGE_FIELDS)

RUNTIME_SYNC_FIELDS = _natural_keys - _MERGE_SET

# 旧 AUTO_* 总开关由仓库发布策略控制；真实时段开关在 GREETING_CONFIG。
# 若把线上旧值回灌到本地，会在部署前悄悄撤销本次“关闭泛问候”的修复。
LOCAL_AUTHORITATIVE_DEPLOY_FIELDS = {
    "AUTO_GREETING",
    "AUTO_GOODNIGHT",
    # 模型池发布时必须以本次已审核清单为准，不能把线上旧索引/旧黑名单回灌回来。
    "CURRENT_MODEL_INDEX",
    "BLACKLISTED_MODELS",
    "BLACKLISTED_MODELS_TS",
    "MODEL_POOL_PREMIUM",
    "MODEL_POOL_STANDARD",
    "MODEL_POOL_LIGHT",
    "AB_TEST_GROUP_A_MODEL",
    "AB_TEST_GROUP_B_MODEL",
}

# 已确认没有运行入口的废弃配置；安全合并时也从生产配置移除，避免幽灵开关。
REMOVED_CONFIG_FIELDS = {
    "STATS_REPORT_CONFIG",
    "NEWS_BROADCAST_CONFIG",
    "AUTO_NEWS",
    "NEWS_HOUR_MORNING",
    "NEWS_HOUR_AFTERNOON",
    "NEWS_HOUR_EVENING",
}


def safe_merge_config(local_cfg: dict, vps_cfg: dict) -> dict:
    """
    安全合并配置：保护敏感字段，其他字段默认以本地为准。
    - PROTECTED_FIELDS: 保留VPS原值，但如果VPS值为空则用本地值
    - 其他字段: 用本地值更新
    部署前会先调用 sync_runtime_fields_from_vps，把线上动态字段同步回本地，
    所以这里可以安全地以本地配置为准，避免线上旧值反向覆盖整理后的新配置。
    """
    merged = dict(vps_cfg)

    for field, value in local_cfg.items():
        if field not in PROTECTED_FIELDS:
            merged[field] = local_cfg[field]

    for field in PROTECTED_FIELDS:
        if field in vps_cfg and vps_cfg[field]:
            merged[field] = vps_cfg[field]
        elif field in local_cfg and local_cfg[field]:
            merged[field] = local_cfg[field]
        elif field in merged and not merged.get(field):
            if field in local_cfg:
                merged[field] = local_cfg[field]

    for field in REMOVED_CONFIG_FIELDS:
        merged.pop(field, None)

    return merged


def _patch_missing_keys(vps_config: dict) -> dict:
    """从config.json.example补齐VPS配置中缺失的键（仅添加，不覆盖已有值）"""
    example_path = Path(__file__).resolve().parent.parent / 'config.json.example'
    if not example_path.exists():
        return vps_config

    try:
        with open(example_path, 'r', encoding='utf-8') as f:
            example_config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[配置补齐] 读取config.json.example失败: {e}")
        return vps_config

    patched = 0
    for key, value in example_config.items():
        if key in PROTECTED_FIELDS:
            continue
        if key not in vps_config:
            vps_config[key] = value
            patched += 1

    for key, value in example_config.items():
        if key in PROTECTED_FIELDS:
            continue
        if isinstance(value, dict) and key in vps_config and isinstance(vps_config[key], dict):
            for sub_key, sub_value in value.items():
                if sub_key not in vps_config[key]:
                    vps_config[key][sub_key] = sub_value
                    patched += 1

    if patched > 0:
        logger.info(f"[配置补齐] 从config.json.example补齐了 {patched} 个缺失键")
    return vps_config


def safe_upload_config(sftp, local_cfg: dict, vps_path: str) -> dict:
    """
    安全部署config.json到VPS：
    1. 下载VPS现有配置
    2. 安全合并（保护密钥）
    3. 从config.json.example补齐缺失键
    4. 以 0600 权限备份 VPS 原配置
    5. 上传到同文件系统私有暂存区后，使用 OpenSSH posix-rename 原子替换
    返回合并后的配置dict
    """
    remote_config = f"{vps_path}/config.json"
    backup_dir = f"{vps_path}/backups"

    vps_cfg = {}
    download_ok = False
    tmp_download = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
    tmp_download_path = tmp_download.name
    tmp_download.close()

    try:
        sftp.get(remote_config, tmp_download_path)
        with open(tmp_download_path, 'r', encoding='utf-8') as f:
            vps_cfg = json.load(f)
        download_ok = True
    except FileNotFoundError:
        logger.warning("  ⚠️ VPS上config.json不存在，将使用本地配置（密钥字段置空）")
    except json.JSONDecodeError as e:
        logger.warning(f"  ⚠️ VPS上config.json解析失败: {e}，将使用本地配置（密钥字段置空）")
    except Exception as e:
        logger.warning(f"  ⚠️ 下载VPS配置失败: {e}，将使用本地配置（密钥字段置空）")
    finally:
        try: os.unlink(tmp_download_path)
        except Exception as e: logger.warning(f"清理临时文件失败: {e}")

    if not vps_cfg:
        if download_ok:
            logger.warning("  ⚠️ VPS配置为空dict，将使用本地配置（密钥字段置空）")
        vps_cfg = dict(local_cfg)
        for field in PROTECTED_FIELDS:
            if field in vps_cfg:
                vps_cfg[field] = ""

    merged = safe_merge_config(local_cfg, vps_cfg)

    merged = _patch_missing_keys(merged)

    operation_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}"
    try:
        ensure_remote_dir(sftp, backup_dir)
        sftp.chmod(backup_dir, 0o700)
        backup_path = f"{backup_dir}/config_{operation_id}.json"
        tmp_bak = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
        json.dump(vps_cfg, tmp_bak, ensure_ascii=False, indent=2)
        tmp_bak.close()
        try:
            sftp.put(tmp_bak.name, backup_path)
            sftp.chmod(backup_path, 0o600)
            backup_mode = sftp.stat(backup_path).st_mode & 0o777
            if backup_mode != 0o600:
                raise RuntimeError(f"VPS配置备份权限不是0600: {oct(backup_mode)}")
        finally:
            try: os.unlink(tmp_bak.name)
            except Exception as e: logger.warning(f"清理备份临时文件失败: {e}")
    except Exception as e:
        raise RuntimeError(f"VPS配置备份失败，拒绝覆盖现有配置: {e}") from e

    tmp_upload = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
    json.dump(merged, tmp_upload, ensure_ascii=False, indent=2)
    tmp_upload.close()

    staging_dir = f"{vps_path}/.deploy-staging"
    staging_config = f"{staging_dir}/config.json.{operation_id}.tmp"
    try:
        ensure_remote_dir(sftp, staging_dir)
        sftp.chmod(staging_dir, 0o700)
        sftp.put(tmp_upload.name, staging_config)
        sftp.chmod(staging_config, 0o600)
        rename = getattr(sftp, "posix_rename", None)
        if not callable(rename):
            raise RuntimeError("SFTP服务器不支持posix-rename，拒绝非原子替换config.json")
        rename(staging_config, remote_config)
        config_mode = sftp.stat(remote_config).st_mode & 0o777
        if config_mode != 0o600:
            raise RuntimeError(f"config.json原子替换后权限不是0600: {oct(config_mode)}")
    except Exception:
        try:
            sftp.remove(staging_config)
        except Exception as cleanup_error:
            logger.debug(f"清理失败的配置暂存文件失败: {cleanup_error}")
        raise
    finally:
        try: os.unlink(tmp_upload.name)
        except Exception as e: logger.warning(f"清理上传临时文件失败: {e}")

    return merged


def fetch_remote_config(sftp, vps_path: str) -> dict:
    """只读拉取VPS当前config.json。"""
    remote_config = f"{vps_path}/config.json"
    tmp_download = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
    tmp_download_path = tmp_download.name
    tmp_download.close()
    try:
        sftp.get(remote_config, tmp_download_path)
        with open(tmp_download_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"拉取VPS配置失败: {e}")
        return {}
    finally:
        try:
            os.unlink(tmp_download_path)
        except Exception as e:
            logger.warning(f"清理临时文件失败: {e}")


def sync_runtime_fields_from_vps(local_cfg: dict, vps_cfg: dict) -> tuple[dict, list]:
    """
    部署前把线上投喂/自然语言修改过的运行时配置拉回本地，避免下一次部署覆盖掉。
    这里遵循“投喂类内容以线上为准”的策略。
    """
    synced = []
    if not vps_cfg:
        return local_cfg, synced

    for field in sorted(RUNTIME_SYNC_FIELDS - LOCAL_AUTHORITATIVE_DEPLOY_FIELDS):
        if field in PROTECTED_FIELDS:
            continue
        if field in vps_cfg and local_cfg.get(field) != vps_cfg.get(field):
            local_cfg[field] = vps_cfg[field]
            synced.append(field)
    return local_cfg, synced


def ensure_remote_dir(sftp, remote_dir: str):
    """确保VPS目录存在，支持多级目录。"""
    current = ""
    for part in remote_dir.strip("/").split("/"):
        current = f"{current}/{part}" if current else f"/{part}"
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)
        except OSError:
            try:
                sftp.mkdir(current)
            except OSError as e:
                logger.warning(f"创建远程目录失败 {current}: {e}")


def sync_env_api_key(sftp, vps_path: str, correct_api_key: str, token: str = ""):
    """
    同步VPS .env文件中的DASHSCOPE_KEY和TG_TOKEN，防止环境变量覆盖config.json的正确值。
    main.py启动时会用.env的DASHSCOPE_KEY覆盖CONFIG["API_KEY"]，
    所以必须确保.env中的key与config.json一致。
    使用SFTP读写.env，避免shell注入风险。

    注意：不会同步占位符值（如 YOUR_DASHSCOPE_API_KEY），只同步真实密钥。
    """
    # 过滤占位符值，不覆盖VPS上的真实密钥
    is_placeholder = lambda v: v.startswith("YOUR_") or v == "" or v is None
    if is_placeholder(correct_api_key):
        correct_api_key = ""  # 不覆盖VPS的DASHSCOPE_KEY
    if is_placeholder(token):
        token = ""  # 不覆盖VPS的TG_TOKEN

    remote_env = f"{vps_path}/.env"
    try:
        tmp_download = tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False, encoding='utf-8')
        tmp_download_path = tmp_download.name
        tmp_download.close()

        try:
            sftp.get(remote_env, tmp_download_path)
            with open(tmp_download_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except FileNotFoundError:
            lines = []
        finally:
            try: os.unlink(tmp_download_path)
            except Exception as e: logger.warning(f"清理临时文件失败: {e}")

        found_api = False
        found_token = False
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("DASHSCOPE_KEY="):
                if correct_api_key:  # 只覆盖非占位符值
                    new_lines.append(f"DASHSCOPE_KEY={correct_api_key}\n")
                else:
                    new_lines.append(line)  # 保留VPS原有值
                found_api = True
            elif stripped.startswith("TG_TOKEN="):
                if token:  # 只覆盖非占位符值
                    new_lines.append(f"TG_TOKEN={token}\n")
                else:
                    new_lines.append(line)  # 保留VPS原有值
                found_token = True
            else:
                new_lines.append(line)
        if not found_api and correct_api_key:
            new_lines.append(f"DASHSCOPE_KEY={correct_api_key}\n")
        if token and not found_token:
            new_lines.append(f"TG_TOKEN={token}\n")

        tmp_upload = tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False, encoding='utf-8')
        tmp_upload.writelines(new_lines)
        tmp_upload.close()

        try:
            sftp.put(tmp_upload.name, remote_env)
        finally:
            try: os.unlink(tmp_upload.name)
            except Exception as e: logger.warning(f"清理临时文件失败: {e}")

        if correct_api_key:
            # 安全脱敏：只显示前 4 + 后 4 位（原 [:12] 泄露过多）
            masked_key = correct_api_key[:4] + "***" + correct_api_key[-4:] if len(correct_api_key) > 8 else "***"
            logger.info(f"  同步.env DASHSCOPE_KEY: {masked_key}")
        if token:
            masked = token[:6] + "..." + token[-4:] if len(token) > 10 else "***"
            logger.info(f"  同步.env TG_TOKEN: {masked}")
    except Exception as e:
        logger.warning(f"  ⚠️ 同步.env失败: {e}")


def upload_files(sftp, local_root: str, vps_path: str, files: list, progress_cb=None):
    """
    上传文件列表到VPS。
    files: [(本地相对路径, VPS绝对路径), ...]
    跳过config.json（必须用safe_upload_config）
    progress_cb: 可选回调函数，参数为(已完成数, 总数)
    """
    uploaded = []
    total = len(files)
    for idx, (local_rel, remote_path) in enumerate(files, 1):
        if local_rel.replace("\\", "/") == "config.json":
            continue
        local_full = os.path.join(local_root, local_rel)
        if os.path.exists(local_full):
            ensure_remote_dir(sftp, posixpath.dirname(remote_path))
            sftp.put(local_full, remote_path)
            uploaded.append(local_rel)
        # 回调通知进度（每20个文件或最后一个文件时触发）
        if progress_cb and (idx % 20 == 0 or idx == total):
            progress_cb(idx, total)
    return uploaded


def _deployment_verification_checks(vps_path: str) -> list[tuple[str, str]]:
    """构造运行态发布门禁；业务探针由调用方按受影响入口另行执行。"""
    remote = shlex.quote(vps_path)
    return [
        # 验证 1：Bot 进程 active
        ("Bot状态", "systemctl is-active mory-assistant"),
        # 验证 2：Dashboard 进程 active
        ("Dashboard状态", "systemctl is-active mory-dashboard"),
        # 验证 3：Dashboard health API 返回 200
        ("Health API", "curl -s -o /dev/null -w '%{http_code}' http://localhost:6616/api/health"),
        # 验证 4：直接读取远端 version.py；health 只判 liveness，不能提供版本证据。
        ("运行版本", f"cd {remote} && python3 -c 'from version import VERSION; print(VERSION)'"),
        # 验证 5：Bot 本次启动窗口无真实错误。
        ("Bot日志", """since=$(systemctl show mory-assistant -p ActiveEnterTimestamp --value) || exit 2; test -n "$since" || { echo STARTUP_TIMESTAMP_UNAVAILABLE; exit 2; }; logs=$(journalctl -u mory-assistant --since "$since" -n 120 --no-pager 2>&1) || { printf '%s\n' "$logs"; exit 2; }; errors=$(printf '%s\n' "$logs" | grep -Ei '\\[(ERROR|CRITICAL)\\]|importerror|modulenotfounderror|traceback|exception' || true); test -z "$errors" || { printf '%s\n' "$errors"; exit 1; }; echo STARTUP_LOG_CLEAN"""),
        # 验证 6：只检查 Dashboard 本次进入 active 后的新日志，避免 systemd 停旧进程时的 gevent 退出噪声误报
        # 仅过滤已实机确认的 logging._removeHandlerRef/gevent 退出栈；其他析构异常和启动失败必须保留。
        ("Dashboard日志", f"""since=$(systemctl show mory-dashboard -p ActiveEnterTimestamp --value) || exit 2; test -n "$since" || {{ echo STARTUP_TIMESTAMP_UNAVAILABLE; exit 2; }}; logs=$(journalctl -u mory-dashboard --since "$since" -n 80 --no-pager 2>&1) || {{ printf '%s\n' "$logs"; exit 2; }}; cd {remote} || exit 2; filtered=$(printf '%s\n' "$logs" | python3 -c 'import sys; from core.deploy_utils import filter_dashboard_teardown_noise as f; sys.stdout.write(f(sys.stdin.read()))') || exit 2; errors=$(printf '%s\n' "$filtered" | grep -Ei '\\[(ERROR|CRITICAL)\\]|importerror|modulenotfounderror|failed to find application|worker failed to boot|traceback|exception' || true); test -z "$errors" || {{ printf '%s\n' "$errors"; exit 1; }}; echo STARTUP_LOG_CLEAN"""),
        # 配置完整性检查
        ("配置完整性", f"""cd {remote} && python3 << 'PYEOF'
import json
c = json.load(open('config.json'))
ok = True
for fld in ['MODEL_POOLS']:
    if fld not in c or not c[fld]:
        print(f'MISSING: ' + fld)
        ok = False
if ok:
    print('ALL CONFIG OK')
PYEOF"""),
        # 凭据只验证 .env 键存在，不输出值，也不要求 config.json 重复存储。
        ("凭据键", f"""cd {remote} && python3 << 'PYEOF'
from dotenv import dotenv_values
env = dotenv_values('.env')
required = ('TG_TOKEN', 'DASHSCOPE_KEY')
missing = [key for key in required if not env.get(key)]
if missing:
    raise SystemExit('ENV_KEYS_MISSING ' + ','.join(missing))
print('ENV_KEYS_OK')
PYEOF"""),
        # DB 完整性；只读 URI，避免验证步骤本身产生写入。
        ("数据库完整性", f"""cd {remote} && python3 << 'PYEOF'
import sqlite3
conn = sqlite3.connect('file:mory.db?mode=ro', uri=True)
integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
foreign_keys = conn.execute('PRAGMA foreign_key_check').fetchall()
if integrity != 'ok' or foreign_keys:
    raise SystemExit(f'DB_INVALID integrity={{integrity}} foreign_keys={{len(foreign_keys)}}')
print('DB_INTEGRITY_OK')
PYEOF"""),
        # 调度 coverage 可读且无陈旧 running；不把历史 metrics 冒充当前注册表。
        ("调度事实", f"""cd {remote} && python3 << 'PYEOF'
import sqlite3, time
conn = sqlite3.connect('file:mory.db?mode=ro', uri=True)
tables = {{row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}}
required = {{'task_execution_history', 'scheduler_metrics'}}
missing = required - tables
if missing:
    raise SystemExit('SCHEDULER_TABLES_MISSING ' + ','.join(sorted(missing)))
cutoff = int(time.time()) - 3600
stale = conn.execute("SELECT COUNT(*) FROM task_execution_history WHERE status='running' AND start_ts < ?", (int(time.time()) - 1800,)).fetchone()[0]
failed = conn.execute("SELECT COUNT(*) FROM task_execution_history WHERE status='failed' AND start_ts >= ?", (cutoff,)).fetchone()[0]
bad_metrics = conn.execute(
    "SELECT COUNT(*) FROM scheduler_metrics "
    "WHERE last_status IN ('error','missed') AND COALESCE(last_run,0) >= ?",
    (cutoff,),
).fetchone()[0]
cumulative_metrics = conn.execute(
    "SELECT COUNT(*) FROM scheduler_metrics WHERE fail_count > 0 OR miss_count > 0"
).fetchone()[0]
history_total = conn.execute("SELECT COUNT(*) FROM task_execution_history").fetchone()[0]
history_latest_start = conn.execute("SELECT MAX(start_ts) FROM task_execution_history").fetchone()[0]
if stale or failed or bad_metrics:
    raise SystemExit(f'SCHEDULER_UNHEALTHY stale_running={{stale}} failed_1h={{failed}} bad_metrics={{bad_metrics}}')
print(
    'SCHEDULER_TRUTH_OK '
    f'coverage=transactional_tasks_only_1h+current_metrics_1h+cumulative_metrics({{cumulative_metrics}}) '
    f'history_total={{history_total}} history_latest_start={{history_latest_start or "none"}} '
    'registry=current_process_not_observed'
)
PYEOF"""),
        # 当前进程至少要有启动注册回执，且启动至今不能出现注册/热重载同步失败。
        ("调度注册", f"""since=$(systemctl show mory-assistant -p ActiveEnterTimestamp --value) || exit 2; test -n "$since" || {{ echo SCHEDULER_STARTUP_TIMESTAMP_UNAVAILABLE; exit 2; }}; logs=$(journalctl -u mory-assistant --since "$since" --no-pager -o cat 2>&1) || {{ printf '%s\n' "$logs"; exit 2; }}; cd {remote} || exit 2; printf '%s\n' "$logs" | python3 -c 'import sys; from core.deploy_utils import scheduler_registry_receipt_from_logs as f; code, receipt = f(sys.stdin.read()); print(receipt); raise SystemExit(code)'"""),
        # root 执行面和敏感文件权限必须读回，不接受部署命令“应该成功”。
        ("权限", f"""test "$(stat -c '%U:%G %a' /etc/systemd/system/mory-assistant.service)" = 'root:root 644' && test "$(stat -c '%U:%G %a' /etc/systemd/system/mory-dashboard.service)" = 'root:root 644' && test "$(stat -c '%a' {remote}/.env)" = '600' && test "$(stat -c '%a' {remote}/config.json)" = '600' && test "$(stat -c '%a' {remote}/mory.db)" = '600' && test "$(stat -c '%U:%G %a' /usr/local/lib/mory-assistant/vps_watchdog.py)" = 'root:root 755' && echo PERMISSIONS_OK"""),
    ]


def verify_deployment(ssh, vps_path: str) -> bool:
    """验证 VPS 运行态发布门禁；真实业务完成仍需受影响入口探针。"""
    from version import VERSION as expected_version

    checks = _deployment_verification_checks(vps_path)

    all_ok = True
    for name, cmd in checks:
        try:
            stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
            out = stdout.read().decode('utf-8', errors='replace').strip()
            err = stderr.read().decode('utf-8', errors='replace').strip()
            exit_code = stdout.channel.recv_exit_status()
            logger.info(f"  [{name}] {out}")
            if exit_code != 0 or err:
                logger.error(f"  ❌ {name} 检查命令失败 rc={exit_code}: {err or out}")
                all_ok = False
                continue
            # 逐项检查是否通过
            if name in {"Bot状态", "Dashboard状态"} and out != "active":
                logger.error(f"  ❌ {name} 返回 {out!r}，预期 active")
                all_ok = False
            elif name == "Health API" and out != "200":
                logger.error(f"  ❌ Health API 返回 {out}，预期 200")
                all_ok = False
            elif name == "运行版本" and out != expected_version:
                logger.error(f"  ❌ VPS 版本 {out or 'none'}，预期 {expected_version}")
                all_ok = False
            elif name in {"Bot日志", "Dashboard日志"}:
                if out != "STARTUP_LOG_CLEAN":
                    logger.error(f"  ❌ {name}中发现错误")
                    all_ok = False
            elif name == "配置完整性" and out != "ALL CONFIG OK":
                all_ok = False
            elif name == "凭据键" and out != "ENV_KEYS_OK":
                all_ok = False
            elif name == "数据库完整性" and out != "DB_INTEGRITY_OK":
                all_ok = False
            elif name == "调度事实" and not out.startswith("SCHEDULER_TRUTH_OK"):
                all_ok = False
            elif name == "调度注册" and not out.startswith("SCHEDULER_REGISTRY_OK"):
                all_ok = False
            elif name == "权限" and out != "PERMISSIONS_OK":
                all_ok = False
            elif 'MISSING' in out or 'inactive' in out.lower() or 'failed' in out.lower() or '未运行' in out:
                all_ok = False
        except Exception as e:
            logger.error(f"  [{name}] 检查失败: {e}")
            all_ok = False

    return all_ok
