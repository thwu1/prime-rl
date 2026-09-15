FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && \
    apt-get install -y postgresql postgresql-client python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY pg_hba.conf /tmp/pg_hba.conf
COPY init_schema.sql /docker-init/init_schema.sql
COPY seed_data.sql /docker-init/seed_data.sql
COPY schema.sql /app/schema.sql
COPY queries.sql /app/queries.sql

RUN PG_VER=$(ls /etc/postgresql/ | head -1) && \
    cp /tmp/pg_hba.conf /etc/postgresql/$PG_VER/main/pg_hba.conf && \
    echo "random_page_cost = 1.1" >> /etc/postgresql/$PG_VER/main/postgresql.conf && \
    pg_ctlcluster $PG_VER main start && \
    until pg_isready -U postgres -q; do sleep 0.5; done && \
    createdb -U postgres eventdb && \
    psql -U postgres -d eventdb -f /docker-init/init_schema.sql && \
    psql -U postgres -d eventdb -f /docker-init/seed_data.sql && \
    psql -U postgres -d eventdb -c 'VACUUM ANALYZE app.events;' && \
    pg_ctlcluster $PG_VER main stop
