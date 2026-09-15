FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    jq \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/config /app/output /app/pipeline

COPY generate_data.py /app/generate_data.py
COPY rules.yaml /app/config/rules.yaml
COPY slos.yaml /app/config/slos.yaml

RUN python3 /app/generate_data.py && rm /app/generate_data.py

WORKDIR /app
