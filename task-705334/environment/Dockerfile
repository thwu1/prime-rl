
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    perl \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/brendangregg/FlameGraph.git /app/FlameGraph && \
    chmod +x /app/FlameGraph/*.pl

WORKDIR /app

COPY profiles/ /app/profiles/
COPY metrics.csv /app/metrics.csv

RUN mkdir -p /app/output
