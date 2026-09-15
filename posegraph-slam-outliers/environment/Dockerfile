
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN mkdir -p /app
COPY generate_dataset.py /tmp/generate_dataset.py
RUN python3 /tmp/generate_dataset.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
COPY --from=builder /app/pose_graph.json /app/pose_graph.json

WORKDIR /app
