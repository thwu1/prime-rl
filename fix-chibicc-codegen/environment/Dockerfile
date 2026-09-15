
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/rui314/chibicc.git /app/chibicc && \
    cd /app/chibicc && \
    git checkout 90d1f7f199cc55b13c7fdb5839d1409806633fdb && \
    rm -rf .git && \
    make

COPY benchmark.c /app/benchmark.c

WORKDIR /app
