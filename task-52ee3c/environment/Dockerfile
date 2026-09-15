
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip dnsutils bind9-utils jq netcat-openbsd && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/zones

COPY zones/example.test.zone /app/zones/example.test.zone
COPY dns_server.py /app/dns_server.py
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

WORKDIR /app
