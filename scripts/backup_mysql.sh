#!/bin/sh
# ============================================================
# DocAgent MySQL 每日备份（在 mysql-backup 容器内经 crond 调用）
# 产物：/backup/mysql_YYYYmmdd_HHMMSS.sql.gz，保留 BACKUP_KEEP_DAYS 天
# 恢复示例：gunzip -c mysql_xxx.sql.gz | mysql -h 127.0.0.1 -P 3307 -u root -p docagent
# ============================================================
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backup}"
MYSQL_HOST="${MYSQL_HOST:-mysql}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:-root}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-docagent123}"
MYSQL_DATABASE="${MYSQL_DATABASE:-docagent}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"

STAMP="$(date +%Y%m%d_%H%M%S)"
FILE="${BACKUP_DIR}/mysql_${STAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

# 备份失败也必须让 crond 记录日志（set -e 下用 if 包装，写日志后退出）
if ! mysqldump -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" \
    -p"$MYSQL_PASSWORD" --single-transaction --routines --triggers \
    --default-character-set=utf8mb4 "$MYSQL_DATABASE" 2>/dev/null | gzip > "$FILE"; then
    echo "$(date '+%F %T') [backup] mysqldump 失败" >&2
    rm -f "$FILE"
    exit 1
fi

echo "$(date '+%F %T') [backup] 完成: $FILE ($(du -h "$FILE" | cut -f1))"

# 清理 N 天前的备份
find "$BACKUP_DIR" -name 'mysql_*.sql.gz' -mtime "+$BACKUP_KEEP_DAYS" -delete
