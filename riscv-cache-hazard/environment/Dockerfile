FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src

COPY src/hazard.sv /app/src/hazard.sv
COPY src/cache.sv /app/src/cache.sv
COPY configs.json /app/configs.json
COPY trace.json /app/trace.json
COPY scenarios.json /app/scenarios.json
COPY schema.json /app/schema.json

WORKDIR /app
