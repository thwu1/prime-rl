FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    postgresql \
    postgresql-contrib \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY pg_custom.conf /tmp/pg_custom.conf
COPY pg_hba_setup.conf /tmp/pg_hba_setup.conf
COPY pg_hba.conf /tmp/pg_hba.conf
COPY setup.sql /tmp/setup.sql
COPY workload.sql /tmp/workload.sql
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Append custom PostgreSQL configuration
RUN PG_CONF=$(find /etc/postgresql -name postgresql.conf | head -1) && \
    cat /tmp/pg_custom.conf >> "$PG_CONF"

# Use trust auth during build to avoid su/psql UID lookup failures in podman
RUN PG_HBA=$(find /etc/postgresql -name pg_hba.conf | head -1) && \
    cp /tmp/pg_hba_setup.conf "$PG_HBA"

# Initialize database: create user, database, schema, data, and simulate workload
RUN PG_VER=$(ls /etc/postgresql/ | head -1) && \
    pg_ctlcluster $PG_VER main start && \
    psql -U postgres -c "CREATE USER admin WITH SUPERUSER PASSWORD 'taskpass';" && \
    psql -U postgres -c "CREATE DATABASE ecommerce OWNER admin;" && \
    psql -U postgres -d ecommerce -f /tmp/setup.sql && \
    psql -U postgres -d ecommerce -f /tmp/workload.sql && \
    pg_ctlcluster $PG_VER main stop

# Replace pg_hba.conf with password-based auth for runtime
RUN PG_HBA=$(find /etc/postgresql -name pg_hba.conf | head -1) && \
    cp /tmp/pg_hba.conf "$PG_HBA"

WORKDIR /app

CMD ["/entrypoint.sh"]
