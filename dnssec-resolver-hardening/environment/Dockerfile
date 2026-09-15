FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    nsd \
    unbound \
    ldnsutils \
    dnsutils \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/dns/zones

COPY zones/ /app/dns/zones/
COPY nsd.conf /app/dns/nsd.conf
COPY scripts/setup_dns.py /app/dns/setup_dns.py
COPY scripts/start.sh /app/dns/start.sh

RUN chmod +x /app/dns/start.sh
RUN python3 /app/dns/setup_dns.py

WORKDIR /app
