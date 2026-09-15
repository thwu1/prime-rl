
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/results

COPY data/network.json /app/data/network.json
COPY data/demand_scenarios.csv /app/data/demand_scenarios.csv
COPY data/config.json /app/data/config.json
COPY data/output_spec.json /app/data/output_spec.json

WORKDIR /app
