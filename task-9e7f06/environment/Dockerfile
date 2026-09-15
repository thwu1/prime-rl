FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/output

COPY gpu.json /app/gpu.json
COPY search_ranges.json /app/search_ranges.json
COPY output_schema.json /app/output_schema.json
COPY db_schema.sql /app/db_schema.sql
COPY build_output.log /app/build_output.log
COPY runner.cu /app/src/runner.cu
COPY kernel_warptiling.cuh /app/src/kernel_warptiling.cuh

WORKDIR /app
