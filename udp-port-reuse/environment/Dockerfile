FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    iproute2 \
    procps \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY echo_server.py /app/echo_server.py
COPY client_naive.py /app/client_naive.py

WORKDIR /app
