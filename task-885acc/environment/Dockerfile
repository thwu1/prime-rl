FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
COPY generate_data.py /tmp/generate_data.py
RUN mkdir -p /app && python3 /tmp/generate_data.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip gcc make libsqlite3-dev sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/tools
COPY --from=builder /app/pose_graph.db /app/pose_graph.db
COPY spec.md /app/SPEC.md
COPY se2_ops.c /app/tools/se2_ops.c
COPY se2_ops.h /app/tools/se2_ops.h
COPY Makefile_se2 /app/tools/Makefile

WORKDIR /app
