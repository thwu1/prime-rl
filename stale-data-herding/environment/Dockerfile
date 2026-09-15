FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip default-jre-headless wget && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/tools && \
    wget -q -O /app/tools/tla2tools.jar \
    "https://github.com/tlaplus/tlaplus/releases/download/v1.8.0/tla2tools.jar"

COPY commit_protocol.tla /app/commit_protocol.tla
COPY commit_protocol.cfg /app/commit_protocol.cfg

WORKDIR /app
