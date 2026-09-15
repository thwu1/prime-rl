FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y postgresql postgresql-client python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Allow trust authentication for all local connections
COPY pg_hba.conf /etc/postgresql/16/main/pg_hba.conf

COPY setup.sql /tmp/setup.sql
RUN mkdir -p /app/queries /app/optimized
COPY queries/ /app/queries/

# Initialize database with schema and data
# Use psql directly instead of su/createuser to avoid podman user namespace issues
RUN pg_ctlcluster 16 main start && \
    psql -U postgres -c "CREATE ROLE root WITH LOGIN SUPERUSER;" && \
    psql -U postgres -c "CREATE ROLE bench WITH LOGIN SUPERUSER;" && \
    psql -U postgres -c "CREATE DATABASE benchdb OWNER bench;" && \
    psql -U bench -d benchdb -f /tmp/setup.sql && \
    pg_ctlcluster 16 main stop

WORKDIR /app
