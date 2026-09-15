#!/bin/bash
# Reliably start MySQL and wait for it to be ready.
# Designed for runtime use in Docker containers where MySQL was
# initialized during build but is not running at container start.

SOCKET=/var/run/mysqld/mysqld.sock

# Ensure required directories exist with correct ownership
mkdir -p /var/run/mysqld /var/log/mysql /var/lib/mysql/tmp
chown mysql:mysql /var/run/mysqld /var/log/mysql /var/lib/mysql/tmp 2>/dev/null || true
chmod 755 /var/run/mysqld
chmod 1777 /tmp 2>/dev/null || true

# Check if MySQL is already running
if mysqladmin --socket="$SOCKET" ping --silent 2>/dev/null; then
    echo "MySQL is already running"
    exit 0
fi

# Remove stale pid/socket files from previous (crashed) runs
rm -f /var/run/mysqld/mysqld.pid "$SOCKET"

# Start MySQL with explicit paths
mysqld \
    --user=mysql \
    --datadir=/var/lib/mysql \
    --socket="$SOCKET" \
    --pid-file=/var/run/mysqld/mysqld.pid \
    --log-error=/var/log/mysql/error.log \
    --tmpdir=/var/lib/mysql/tmp \
    &
MYSQL_PID=$!

# Wait for MySQL to become ready (up to 90 seconds)
MYSQL_READY=0
for i in $(seq 1 90); do
    if mysqladmin --socket="$SOCKET" ping --silent 2>/dev/null; then
        MYSQL_READY=1
        break
    fi
    # Check if mysqld process died
    if ! kill -0 "$MYSQL_PID" 2>/dev/null; then
        echo "ERROR: mysqld process exited unexpectedly"
        tail -30 /var/log/mysql/error.log 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

if [ "$MYSQL_READY" -ne 1 ]; then
    echo "ERROR: MySQL did not become ready within 90 seconds"
    tail -30 /var/log/mysql/error.log 2>/dev/null || true
    exit 1
fi

echo "MySQL is running (pid=$MYSQL_PID)"
