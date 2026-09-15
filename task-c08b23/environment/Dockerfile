
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/test_results /app/output

COPY coefficients.json /app/data/coefficients.json
COPY test_results/ /app/data/test_results/
COPY spec.md /app/spec.md
COPY buggy_engine.py /app/buggy_engine.py
COPY oracle_alpha.json /app/data/oracle_alpha.json
COPY beta_data.sql /tmp/beta_data.sql
RUN sqlite3 /app/data/beta_results.db < /tmp/beta_data.sql && rm /tmp/beta_data.sql

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
