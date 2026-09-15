#!/bin/bash

pip3 install PyMySQL==1.1.1 -q

# Kill any existing MySQL processes
pkill -9 mysqld 2>/dev/null || true
sleep 2

# Remove stale socket/pid files
rm -f /tmp/mysql.sock /tmp/mysql.pid

# Fix /tmp permissions and ensure MySQL runtime directories exist
chmod 1777 /tmp 2>/dev/null || true
mkdir -p /var/run/mysqld /var/log/mysql /var/lib/mysql-tmp
chown mysql:mysql /var/run/mysqld 2>/dev/null
chown mysql:mysql /var/log/mysql 2>/dev/null
chown mysql:mysql /var/lib/mysql-tmp 2>/dev/null
chmod 1777 /var/lib/mysql-tmp

# Ensure MySQL data directory has correct permissions
chown -R mysql:mysql /var/lib/mysql 2>/dev/null

# Clear error log so we only see fresh errors
truncate -s 0 /var/log/mysql/error.log 2>/dev/null || true

# Start MySQL with explicit options for container compatibility
mysqld --user=mysql \
       --socket=/tmp/mysql.sock \
       --pid-file=/tmp/mysql.pid \
       --innodb-use-native-aio=0 \
       --tmpdir=/var/lib/mysql-tmp \
       --skip-networking \
       --log-error=/var/log/mysql/error.log &

for i in $(seq 1 60); do
    mysqladmin --socket=/tmp/mysql.sock -u root ping 2>/dev/null && break
    sleep 1
done

# Verify MySQL is running
if ! mysqladmin --socket=/tmp/mysql.sock -u root ping 2>/dev/null; then
    echo "ERROR: MySQL failed to start"
    if [ -f /var/log/mysql/error.log ]; then
        echo "=== MySQL error log ==="
        tail -50 /var/log/mysql/error.log
    fi
    exit 1
fi

python3 /solution/reconcile.py
