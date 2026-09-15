FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/affinity_engine /app/configs
COPY app/affinity_engine/__init__.py /app/affinity_engine/__init__.py
COPY app/affinity_engine/topology.py /app/affinity_engine/topology.py
COPY app/affinity_engine/placement.py /app/affinity_engine/placement.py
COPY app/affinity_engine/affinity.py /app/affinity_engine/affinity.py
COPY app/affinity_engine/env_generator.py /app/affinity_engine/env_generator.py
COPY app/affinity_engine/diagnostics.py /app/affinity_engine/diagnostics.py
COPY app/configs/dual_epyc_nps2.json /app/configs/dual_epyc_nps2.json
COPY app/configs/dual_xeon_nps1.json /app/configs/dual_xeon_nps1.json
COPY app/configs/single_xeon_ht.json /app/configs/single_xeon_ht.json
COPY app/main.py /app/main.py

WORKDIR /app
