FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && \
    apt-get install -y python3 python3-pip tshark gcc binutils sqlite3 && \
    rm -rf /var/lib/apt/lists/*

COPY build/ /tmp/build/
COPY crypto/ /app/crypto/

RUN python3 /tmp/build/generate_data.py

RUN mkdir -p /app/bin && \
    gcc -O0 -o /app/bin/mac_engine /tmp/build/mac_engine.c && \
    chmod +x /app/bin/mac_engine

RUN rm -rf /tmp/build

RUN mkdir -p /app/output
WORKDIR /app
