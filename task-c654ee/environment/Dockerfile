FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && \
    apt-get install -y mysql-server python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Override MySQL socket/pid, disable native AIO, set custom tmpdir for container compat
COPY mysql_socket.cnf /etc/mysql/mysql.conf.d/zzz-socket.cnf

# Ensure runtime, data, log, and tmp directories exist with correct permissions
RUN chmod 1777 /tmp && \
    mkdir -p /var/run/mysqld /var/log/mysql /var/lib/mysql-tmp /app/binlogs && \
    chown mysql:mysql /var/run/mysqld && \
    chmod 755 /var/run/mysqld && \
    chown mysql:mysql /var/log/mysql && \
    chown mysql:mysql /var/lib/mysql-tmp && \
    chmod 1777 /var/lib/mysql-tmp && \
    chown -R mysql:mysql /var/lib/mysql

COPY setup_db.sql /app/setup_db.sql
COPY schema.sql /app/schema.sql
COPY metadata.json /app/metadata.json
COPY east_dc.binlog.txt /app/binlogs/east_dc.binlog.txt
COPY west_dc.binlog.txt /app/binlogs/west_dc.binlog.txt

# Start MySQL, load base data, shut down cleanly
RUN rm -f /tmp/mysql.sock /tmp/mysql.pid && \
    mysqld --user=mysql --innodb-use-native-aio=0 --skip-networking \
           --tmpdir=/var/lib/mysql-tmp \
           --socket=/tmp/mysql.sock --pid-file=/tmp/mysql.pid \
           --log-error=/var/log/mysql/error.log & \
    for i in $(seq 1 60); do \
        mysqladmin --socket=/tmp/mysql.sock -u root ping 2>/dev/null && break; \
        sleep 1; \
    done && \
    mysqladmin --socket=/tmp/mysql.sock -u root ping && \
    mysql --socket=/tmp/mysql.sock -u root < /app/setup_db.sql && \
    mysqladmin --socket=/tmp/mysql.sock -u root shutdown && \
    for i in $(seq 1 30); do \
        test ! -f /tmp/mysql.pid && break; \
        sleep 1; \
    done && \
    rm -f /tmp/mysql.sock /tmp/mysql.pid && \
    chown -R mysql:mysql /var/lib/mysql && \
    truncate -s 0 /var/log/mysql/error.log

WORKDIR /app

CMD ["sleep", "infinity"]
