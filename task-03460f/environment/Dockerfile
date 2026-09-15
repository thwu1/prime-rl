FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install "sqlmesh[duckdb]==0.235.3"

RUN mkdir -p /app/models/seeds /app/models/staging /app/models/intermediate /app/models/analytics /app/audits /app/tests /app/seeds

COPY config.yaml /app/config.yaml
COPY seeds /app/seeds
COPY models /app/models
COPY audits /app/audits
COPY tests /app/tests

WORKDIR /app
