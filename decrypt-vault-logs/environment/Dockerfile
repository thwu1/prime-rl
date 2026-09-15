FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install cryptography==44.0.0 -q

COPY generate_db.py /tmp/generate_db.py
RUN python3 /tmp/generate_db.py

# ── Final stage: only generated artifacts and source code survive ────
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 openssl xxd && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/data/audit.db /app/data/audit.db
COPY --from=builder /app/keys/ /app/keys/
COPY --from=builder /app/config/ /app/config/
COPY vault_logger/ /app/vault_logger/

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 cryptography==44.0.0
