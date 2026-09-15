
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install duckdb==1.1.3

RUN mkdir -p /app/pipeline /app/config /app/logs

COPY setup_tree.py /app/setup_tree.py
COPY pipeline/ /app/pipeline/
COPY config/ /app/config/
COPY logs/ /app/logs/

RUN python3 /app/setup_tree.py

WORKDIR /app
ENV PYTHONPATH=/app
