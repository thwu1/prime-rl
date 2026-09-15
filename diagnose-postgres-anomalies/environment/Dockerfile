FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    postgresql \
    postgresql-client \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY init_db.sql /tmp/init_db.sql
COPY workload.sql /app/workload.sql
COPY start_pg.sh /app/start_pg.sh
RUN chmod +x /app/start_pg.sh

# Configure trust authentication BEFORE init so we can connect via TCP as any user
RUN PG_HBA=$(find /etc/postgresql -name pg_hba.conf | head -1) && \
    echo "local all all trust" > "$PG_HBA" && \
    echo "host all all 127.0.0.1/32 trust" >> "$PG_HBA" && \
    echo "host all all ::1/128 trust" >> "$PG_HBA"

# Initialize the benchmark database using TCP connection to avoid
# su/user-namespace issues in podman builds
RUN service postgresql start && \
    until pg_isready -h 127.0.0.1 -U postgres -q; do sleep 1; done && \
    psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE benchmark" && \
    psql -U postgres -h 127.0.0.1 -d benchmark -f /tmp/init_db.sql && \
    service postgresql stop && \
    rm -f /tmp/init_db.sql

WORKDIR /app
CMD ["/app/start_pg.sh"]
