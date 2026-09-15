FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY cluster_state.json /app/cluster_state.json
COPY broker_jmx.json /app/broker_jmx.json
COPY connect_status.json /app/connect_status.json
COPY acl_dump.txt /app/acl_dump.txt

WORKDIR /app

