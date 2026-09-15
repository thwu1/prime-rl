FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    mysql-server \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages needed for the task environment
RUN pip3 install pymysql==1.1.1 pyyaml==6.0.2 -q

# Disable native AIO, skip binlog, set tmpdir for container compatibility
COPY mysql-no-aio.cnf /etc/mysql/mysql.conf.d/99-no-aio.cnf

# Ensure /tmp and custom MySQL tmpdir have correct permissions
RUN chmod 1777 /tmp && \
    mkdir -p /var/lib/mysql/tmp && \
    chown mysql:mysql /var/lib/mysql/tmp

# Copy setup files
COPY schema.sql /tmp/schema.sql
COPY populate_data.py /tmp/populate_data.py
COPY init_mysql.sh /tmp/init_mysql.sh

# Copy app files that define the task starting state
COPY config.yaml /app/config.yaml
COPY vhash.py /app/vhash.py
COPY router.py /app/router.py

# Copy MySQL startup helper for runtime use
COPY ensure_mysql.sh /usr/local/bin/ensure-mysql.sh
RUN chmod +x /usr/local/bin/ensure-mysql.sh

# Initialize MySQL, create schema, populate data
RUN chmod +x /tmp/init_mysql.sh && /tmp/init_mysql.sh

# Ensure directories persist for runtime MySQL startup
RUN mkdir -p /var/log/mysql /var/run/mysqld /var/lib/mysql/tmp && \
    chown mysql:mysql /var/log/mysql /var/run/mysqld /var/lib/mysql/tmp && \
    chmod 1777 /tmp

WORKDIR /app

