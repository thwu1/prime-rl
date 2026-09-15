
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    coinor-cbc \
    jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY game.py /app/game.py
COPY evaluate.py /app/evaluate.py
COPY generate_instances.py /app/generate_instances.py

RUN python3 /app/generate_instances.py
