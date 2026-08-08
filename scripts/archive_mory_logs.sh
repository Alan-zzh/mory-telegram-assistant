#!/usr/bin/env bash
# mory.log 轮转文件每日归档，保留 14 天（F2 日志保留修复）
# VPS 部署实例：/home/ubuntu/bin/archive_mory_logs.sh（cron: /etc/cron.d/mory-log-archive 每日 03:30）
set -u
DEST=/home/ubuntu/backup/logs
mkdir -p "$DEST"
cd /home/ubuntu/mory_assistant || exit 1
if ls mory.log.[0-9]* >/dev/null 2>&1; then
  tar -czf "$DEST/mory-$(date +%Y%m%d).tar.gz" mory.log.[0-9]* && rm -f mory.log.[0-9]*
fi
find "$DEST" -name 'mory-*.tar.gz' -mtime +14 -delete
