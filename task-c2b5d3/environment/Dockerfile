FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY data/ft06.txt /app/data/ft06.txt
COPY data/ft10.txt /app/data/ft10.txt
COPY data/ft20.txt /app/data/ft20.txt
COPY data/la01.txt /app/data/la01.txt
COPY data/abz7.txt /app/data/abz7.txt

WORKDIR /app
