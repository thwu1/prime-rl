FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/bin

COPY archsim /app/bin/archsim
RUN chmod +x /app/bin/archsim

COPY init_db.sql /tmp/init_db.sql
RUN sqlite3 /app/workloads.db < /tmp/init_db.sql && rm /tmp/init_db.sql

COPY chip_constraints.toml /app/chip_constraints.toml

ENV PATH="/app/bin:${PATH}"

WORKDIR /app
