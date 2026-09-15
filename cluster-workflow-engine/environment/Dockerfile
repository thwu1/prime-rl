FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    curl \
    jq \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/workflows

COPY cluster.json /app/cluster.json
COPY node_simulator.py /app/node_simulator.py
COPY webhook_server.py /app/webhook_server.py
COPY spec.md /app/spec.md
COPY workflows/rolling_restart.yaml /app/workflows/rolling_restart.yaml
COPY workflows/parallel_cleanup.yaml /app/workflows/parallel_cleanup.yaml
COPY workflows/unrecoverable_test.yaml /app/workflows/unrecoverable_test.yaml

WORKDIR /app
