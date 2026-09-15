FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    postgresql \
    postgresql-contrib \
    python3-pip \
    sudo \
    && rm -rf /var/lib/apt/lists/* \
    && chmod 644 /etc/passwd \
    && PG_VERSION=$(ls /etc/postgresql/) \
    && echo "local all all trust" > "/etc/postgresql/$PG_VERSION/main/pg_hba.conf" \
    && echo "host all all 127.0.0.1/32 trust" >> "/etc/postgresql/$PG_VERSION/main/pg_hba.conf" \
    && echo "host all all ::1/128 trust" >> "/etc/postgresql/$PG_VERSION/main/pg_hba.conf"

WORKDIR /app

COPY bloat_estimate.sql /app/bloat_estimate.sql
COPY index_bloat_estimate.sql /app/index_bloat_estimate.sql

