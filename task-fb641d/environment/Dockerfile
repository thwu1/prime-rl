FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y python3 python3-pip dnsutils tshark tcpdump xxd && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/zones
COPY zones/example.com.zone /app/zones/example.com.zone
COPY dns_server_buggy.py /app/dns_server.py

WORKDIR /app
