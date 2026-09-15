
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-yaml \
    iproute2 \
    nftables \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY app/topology.yaml /app/topology.yaml
COPY app/traffic_demands.yaml /app/traffic_demands.yaml
COPY app/sla_requirements.yaml /app/sla_requirements.yaml
COPY app/bandwidth_spec.yaml /app/bandwidth_spec.yaml
COPY app/tc_generator.py /app/tc_generator.py
