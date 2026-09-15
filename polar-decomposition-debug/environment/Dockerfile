FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PYTHONPATH=/app

RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/polar_decomp

COPY app/polar_decomp/__init__.py /app/polar_decomp/__init__.py
COPY app/polar_decomp/coefficients.py /app/polar_decomp/coefficients.py
COPY app/polar_decomp/standard_ns.py /app/polar_decomp/standard_ns.py
COPY app/polar_decomp/gram_ns.py /app/polar_decomp/gram_ns.py
COPY app/polar_decomp/stability.py /app/polar_decomp/stability.py
COPY app/polar_decomp/restart_finder.py /app/polar_decomp/restart_finder.py
COPY app/schema.sql /app/schema.sql
COPY app/init_db.sql /app/init_db.sql

RUN sqlite3 /app/workloads.db < /app/init_db.sql

WORKDIR /app
