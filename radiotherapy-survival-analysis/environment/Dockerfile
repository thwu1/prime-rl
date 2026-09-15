FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-pip \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY data/hnscc.csv /app/data/hnscc.csv
COPY output_schema.json /app/output_schema.json

WORKDIR /app
