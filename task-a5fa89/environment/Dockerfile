FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder

RUN apt-get update && apt-get install -y python3 sqlite3 && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /app
COPY setup_db.py /tmp/setup_db.py
RUN python3 /tmp/setup_db.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    xxd \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/evidence.db /app/evidence.db
COPY target_queries.sql /app/target_queries.sql

RUN mkdir -p /app/candidate_strategies
COPY strategy_a.sql /app/candidate_strategies/strategy_a.sql
COPY strategy_b.sql /app/candidate_strategies/strategy_b.sql
COPY strategy_c.sql /app/candidate_strategies/strategy_c.sql

WORKDIR /app
