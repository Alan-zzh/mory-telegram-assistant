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

import json, logging, os, posixpath, tempfile, time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("deploy_utils")

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
    4. 备份VPS原配置
    5. 上传合并后配置
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

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        try: sftp.stat(backup_dir)
        except FileNotFoundError:
            sftp.mkdir(backup_dir)
        except OSError:
            sftp.mkdir(backup_dir)
        try: sftp.stat(backup_dir)
        except FileNotFoundError:
            logger.debug(f"备份目录验证跳过: {backup_dir}")
        backup_path = f"{backup_dir}/config_{ts}.json"
        tmp_bak = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
        json.dump(vps_cfg, tmp_bak, ensure_ascii=False, indent=2)
        tmp_bak.close()
        try:
            sftp.put(tmp_bak.name, backup_path)
        finally:
            try: os.unlink(tmp_bak.name)
            except Exception as e: logger.warning(f"清理备份临时文件失败: {e}")
    except Exception as e:
        logger.warning(f"VPS配置备份失败: {e}")

    tmp_upload = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
    json.dump(merged, tmp_upload, ensure_ascii=False, indent=2)
    tmp_upload.close()

    try:
        sftp.put(tmp_upload.name, remote_config)
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

    for field in sorted(RUNTIME_SYNC_FIELDS):
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


def verify_deployment(ssh, vps_path: str) -> bool:
    """验证VPS部署结果，返回True表示成功

    涵盖 AGENTS.md 教训 #10 定义的 4 步验证标准：
    1. mory-assistant active
    2. mory-dashboard active
    3. health API 返回 200
    4. 日志无 ImportError
    """
    checks = [
        # 验证 1：Bot 进程 active
        ("Bot状态", "sudo systemctl is-active mory-assistant"),
        # 验证 2：Dashboard 进程 active
        ("Dashboard状态", "sudo systemctl is-active mory-dashboard"),
        # 验证 3：Dashboard health API 返回 200
        ("Health API", "curl -s -o /dev/null -w '%{http_code}' http://localhost:6616/api/health"),
        # 验证 4：只检查 Dashboard 本次进入 active 后的新日志，避免 systemd 停旧进程时的 gevent 退出噪声误报
        # awk 按整块剔除 gevent 优雅停机噪声（Exception ignored in ... greenlet is being finalized），逐行 grep -v 会漏掉 Traceback 上下文行
        ("Dashboard日志", """since=$(systemctl show mory-dashboard -p ActiveEnterTimestamp --value); journalctl -u mory-dashboard --since "$since" -n 80 --no-pager 2>/dev/null | awk '/Exception ignored in/{skip=1} /greenlet is being finalized/{skip=0; next} !skip' | grep -Ei 'importerror|modulenotfounderror|failed to find application|worker failed to boot|traceback|exception|error' || echo '✅ 无报错'"""),
        # 配置完整性检查
        ("配置完整性", f"""cd {vps_path} && python3 << 'PYEOF'
import json
c = json.load(open('config.json'))
ok = True
for fld in ['TOKEN', 'API_KEY', 'MODEL_POOLS']:
    if fld not in c or not c[fld]:
        print(f'MISSING: ' + fld)
        ok = False
if ok:
    print('ALL CONFIG OK')
PYEOF"""),
    ]

    all_ok = True
    for name, cmd in checks:
        try:
            stdin, stdout, stderr = ssh.exec_command(cmd, timeout=15)
            out = stdout.read().decode('utf-8', errors='replace').strip()
            logger.info(f"  [{name}] {out}")
            # 逐项检查是否通过
            if name == "Health API":
                if out != "200":
                    logger.error(f"  ❌ Health API 返回 {out}，预期 200")
                    all_ok = False
            elif name == "Dashboard日志":
                if "✅" not in out and out.strip():
                    logger.error("  ❌ Dashboard 日志中发现错误")
                    all_ok = False
            elif 'MISSING' in out or 'inactive' in out.lower() or 'failed' in out.lower() or '未运行' in out:
                all_ok = False
        except Exception as e:
            logger.error(f"  [{name}] 检查失败: {e}")
            all_ok = False

    return all_ok
