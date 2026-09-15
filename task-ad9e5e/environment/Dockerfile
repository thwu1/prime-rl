FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    postgresql \
    postgresql-contrib \
    python3-pip \
    sudo \
    && rm -rf /var/lib/apt/lists/*

COPY pg_hba.conf /etc/postgresql/16/main/pg_hba.conf
RUN chown postgres:postgres /etc/postgresql/16/main/pg_hba.conf

COPY setup.sql /tmp/setup.sql
COPY prepare_txn.sql /tmp/prepare_txn.sql
COPY create_bloat.sql /tmp/create_bloat.sql

RUN pg_ctlcluster 16 main start && \
    sleep 2 && \
    psql -U postgres -c "ALTER SYSTEM SET max_prepared_transactions = 10;" && \
    pg_ctlcluster 16 main restart && \
    sleep 2 && \
    psql -U postgres -f /tmp/setup.sql && \
    psql -U postgres -f /tmp/prepare_txn.sql && \
    psql -U postgres -f /tmp/create_bloat.sql && \
    psql -U postgres -c "ALTER SYSTEM SET autovacuum_vacuum_cost_delay = '50ms';" && \
    psql -U postgres -c "ALTER SYSTEM SET autovacuum_vacuum_cost_limit = 50;" && \
    psql -U postgres -c "ALTER SYSTEM SET maintenance_work_mem = '32MB';" && \
    pg_ctlcluster 16 main stop && \
    rm -f /tmp/setup.sql /tmp/prepare_txn.sql /tmp/create_bloat.sql

RUN mkdir -p /app

WORKDIR /app
