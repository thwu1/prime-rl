
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    g++ make \
    jq \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY solvers/ /app/solvers/
COPY instances/ /app/instances/
COPY proposed/ /app/proposed/
COPY problem.md /app/problem.md
COPY schema.sql /app/schema.sql

RUN mkdir -p /app/results /app/evaluations

WORKDIR /app
