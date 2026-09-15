FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip gcc make sqlite3 gnuplot-nox binutils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/engine

COPY kalah_engine.c /app/engine/kalah_engine.c
COPY Makefile /app/engine/Makefile

RUN cd /app/engine && make && cp kalah-engine /app/kalah-engine

COPY problems.json /app/problems.json

WORKDIR /app
