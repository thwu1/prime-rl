FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    perl \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/brendangregg/FlameGraph.git /app/FlameGraph && \
    chmod +x /app/FlameGraph/*.pl

COPY data/ /app/data/

RUN mkdir -p /app/output

WORKDIR /app
