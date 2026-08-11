# ============================================================
# DocAgent MySQL 备份容器（alpine + mariadb-client + busybox crond）
# 每日 03:00 执行 scripts/backup_mysql.sh → ./data/backup/mysql_*.sql.gz
# ============================================================

FROM alpine:3.20

RUN apk add --no-cache mariadb-client

COPY scripts/backup_mysql.sh /usr/local/bin/backup_mysql.sh
RUN chmod +x /usr/local/bin/backup_mysql.sh

# 每日 03:00 备份（容器内时区默认 UTC，如需本地时区可挂载 /etc/localtime）
RUN echo "0 3 * * * /usr/local/bin/backup_mysql.sh >> /var/log/backup_mysql.log 2>&1" \
    > /etc/crontabs/root

CMD ["crond", "-f", "-l", "8"]
