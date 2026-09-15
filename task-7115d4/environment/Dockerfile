
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder

RUN apt-get update && apt-get install -y python3 && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /app
COPY setup_db.py /tmp/setup_db.py
RUN python3 /tmp/setup_db.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/corpus.db /app/corpus.db
COPY spec.md /app/spec.md
COPY tools/ /app/tools/

WORKDIR /app
