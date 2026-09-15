
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY topology.json /app/topology.json
COPY validate.py /app/validate.py
COPY configs/ /app/network_state/configs/
COPY state/ /app/network_state/state/
COPY proposals/ /app/proposals/

RUN chmod +x /app/validate.py

WORKDIR /app
