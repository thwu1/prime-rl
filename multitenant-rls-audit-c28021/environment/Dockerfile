FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    postgresql \
    python3-pip \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Configure trust authentication for local connections
RUN PG_HBA=$(find /etc/postgresql -name pg_hba.conf | head -1) && \
    printf "local all all trust\nhost all all 127.0.0.1/32 trust\nhost all all ::1/128 trust\n" > "$PG_HBA"

COPY schema.sql /app/schema.sql
COPY policies.sql /app/policies.sql
COPY setup.sh /app/setup.sh
RUN chmod +x /app/setup.sh

WORKDIR /app
