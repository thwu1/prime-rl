
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/system /app/model /app/deploy

COPY system/cpuinfo /app/system/cpuinfo
COPY system/numa_topology.json /app/system/numa_topology.json
COPY system/gpu_inventory.json /app/system/gpu_inventory.json
COPY model/config.json /app/model/config.json
COPY model/activation_profile.json /app/model/activation_profile.json
COPY model/vram_profile.json /app/model/vram_profile.json
COPY deploy/launch_config.json /app/deploy/launch_config.json
COPY deploy/error.log /app/deploy/error.log
COPY expected_schema.json /app/expected_schema.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
