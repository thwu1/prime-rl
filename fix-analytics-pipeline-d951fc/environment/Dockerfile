FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    postgresql \
    postgresql-client \
    python3-pip \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Configure PostgreSQL for local trust authentication
RUN PG_HBA=$(find /etc/postgresql -name pg_hba.conf | head -1) && \
    echo "local all all trust" > "$PG_HBA" && \
    echo "host all all 127.0.0.1/32 trust" >> "$PG_HBA" && \
    echo "host all all ::1/128 trust" >> "$PG_HBA"

# Ensure PostgreSQL listens on localhost for TCP connections
RUN PG_CONF=$(find /etc/postgresql -name postgresql.conf | head -1) && \
    echo "listen_addresses = 'localhost'" >> "$PG_CONF"

WORKDIR /app
COPY clubdata.sql /app/clubdata.sql
COPY analytics.sql /app/analytics.sql
