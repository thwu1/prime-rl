#!/bin/bash
set -e

SOCKET=/var/run/mysqld/mysqld.sock

# Ensure required directories exist
mkdir -p /var/run/mysqld /var/log/mysql /var/lib/mysql/tmp
chown mysql:mysql /var/run/mysqld /var/log/mysql /var/lib/mysql/tmp
chmod 755 /var/run/mysqld
chmod 1777 /tmp

# Initialize MySQL data directory if not already done
if [ ! -d "/var/lib/mysql/mysql" ]; then
    mysqld --initialize-insecure --user=mysql --datadir=/var/lib/mysql
fi

# Start MySQL with tmpdir override
mysqld --user=mysql --datadir=/var/lib/mysql --socket="$SOCKET" \
    --pid-file=/var/run/mysqld/mysqld.pid --tmpdir=/var/lib/mysql/tmp &
MYSQL_PID=$!

# Wait for MySQL to be ready (up to 60 seconds)
for i in $(seq 1 60); do
    if mysqladmin --socket="$SOCKET" ping --silent 2>/dev/null; then
        break
    fi
    if ! kill -0 "$MYSQL_PID" 2>/dev/null; then
        echo "MySQL process died during startup"
        cat /var/log/mysql/error.log 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

mysqladmin --socket="$SOCKET" ping --silent || { echo "MySQL failed to start"; exit 1; }

# Create application user with password-based auth
mysql --socket="$SOCKET" -u root -e "CREATE USER IF NOT EXISTS 'bench'@'localhost' IDENTIFIED BY 'bench123';"
mysql --socket="$SOCKET" -u root -e "GRANT ALL PRIVILEGES ON *.* TO 'bench'@'localhost' WITH GRANT OPTION;"
mysql --socket="$SOCKET" -u root -e "FLUSH PRIVILEGES;"

# Run schema
mysql --socket="$SOCKET" -u bench -pbench123 < /tmp/schema.sql

# Populate data
python3 /tmp/populate_data.py

# Stop MySQL cleanly and wait for process exit
mysqladmin --socket="$SOCKET" -u root shutdown
wait $MYSQL_PID 2>/dev/null || true
sleep 1

# Verify MySQL has stopped
if kill -0 "$MYSQL_PID" 2>/dev/null; then
    kill "$MYSQL_PID" 2>/dev/null || true
    sleep 2
fi

echo "MySQL initialization complete"
