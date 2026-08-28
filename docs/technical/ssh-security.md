# SSH 安全边界

项目使用 Paramiko 连接 VPS，所有连接参数统一由 `core/vps_config.py` 提供。

## RSA+SHA-1 临时防护

Paramiko 4.0.0 受 PYSEC-2026-2858（CVE-2026-44405）影响；截至 2026-08-24，PyPI 尚无包含上游修复的新版。项目因此在每个连接上禁用 `ssh-rsa` 签名算法，同时保留 `rsa-sha2-256`、`rsa-sha2-512` 和其他现代算法。

`tests/unit/test_paramiko_sha1_mitigation.py` 会扫描 `core/`、`dashboard/`、`scripts/`、`runtime/` 的直接 Paramiko 连接，任何未接中央防护的新入口都会让 CI 失败。`pip-audit` 只对这一条已补偿风险使用显式例外；上游发布修复版后应升级依赖并删除例外。

该防护可能拒绝只支持 RSA+SHA-1 的老旧 SSH 服务端；项目 VPS 必须支持现代 RSA-SHA2 或 Ed25519。
