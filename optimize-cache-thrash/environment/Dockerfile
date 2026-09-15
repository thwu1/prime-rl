FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y gcc make python3-pip valgrind && \
    rm -rf /var/lib/apt/lists/*

COPY app/ /app/

RUN mkdir -p /app/.original && \
    cp /app/main.c /app/pipeline.c /app/pipeline.h /app/Makefile /app/.original/ && \
    cd /app/.original && make

WORKDIR /app

