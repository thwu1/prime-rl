
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    postgresql \
    postgresql-client \
    python3-pip \
    sudo \
    && rm -rf /var/lib/apt/lists/*

COPY schema.sql /app/schema.sql
COPY setup_db.sh /app/setup_db.sh
COPY ensure_db.sh /app/ensure_db.sh
RUN chmod +x /app/setup_db.sh /app/ensure_db.sh && /app/setup_db.sh

WORKDIR /app
