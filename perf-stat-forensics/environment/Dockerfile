FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip git perl && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/brendangregg/FlameGraph.git /app/FlameGraph && \
    chmod +x /app/FlameGraph/*.pl

RUN mkdir -p /app/captures /app/config

COPY captures/ /app/captures/
COPY config/ /app/config/

WORKDIR /app
