FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data
COPY catalog.json /app/data/catalog.json
COPY output_spec.json /app/output_spec.json

WORKDIR /app
