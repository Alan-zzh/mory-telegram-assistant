# 服务器重装后一键恢复说明

这份文件是给“服务器已经重装干净，本地保留了小软件完整数据”的场景用的。

## 先记住一句话

重装后不要急着把旧服务器里的程序原样搬回去。只从本地可信备份恢复代码、数据、配置，并重新生成服务器密钥和账号密码。

## 重装后恢复顺序

1. 准备一台干净服务器
   - 系统已重装。
   - SSH 能登录。
   - 防火墙只开放必要端口。
   - 旧服务器密码、旧密钥、旧 token 全部作废。

2. 在本地填写配置
   - 复制 `restore_config.example.json` 为 `restore_config.json`。
   - 填服务器 IP、SSH 用户、项目目录、要上传的数据目录、启动命令、检查地址。
   - 不要把真实密码、密钥、token 写进 Git。

3. 先演练

   ```bash
   python scripts/restore_after_reinstall.py --config restore_config.json --dry-run
   ```

4. 正式恢复

   ```bash
   python scripts/restore_after_reinstall.py --config restore_config.json
   ```

5. 恢复后检查
   - 服务进程是否启动。
   - 页面或接口是否能访问。
   - 数据是否完整。
   - 日志里是否还有异常登录、陌生计划任务、陌生二进制文件。

## 推荐恢复原则

- 代码从本地可信目录上传，不从旧服务器复制。
- 数据只恢复业务数据，不恢复旧系统账号、SSH 配置、计划任务、启动项。
- `.env` 这类敏感配置要重建，尤其是数据库密码、后台密码、API Key、Webhook Secret。
- 恢复后立刻更新 `CHANGELOG.md`、`VERSION.md`、`AI_DEBUG_HISTORY.md`，记录这次事故和恢复动作。

## 我下次可以直接做什么

你重装好服务器后，直接把这些信息发我：

- 服务器 IP
- SSH 用户名
- SSH 端口
- 本地数据目录在哪
- 服务启动方式：Docker Compose、systemd、PM2、Python、Node、还是别的
- 域名或健康检查地址

然后说：“按恢复脚本一键恢复上去。”

我会先 dry-run，再正式上传、启动、检查。
