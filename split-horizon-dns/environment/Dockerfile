FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    bind9 \
    bind9-utils \
    dnsutils \
    iproute2 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app /etc/bind/zones/internal /etc/bind/zones/external

COPY named.conf.broken /etc/bind/named.conf
COPY db.internal.forward /etc/bind/zones/internal/db.infra.example.com
COPY db.external.forward /etc/bind/zones/external/db.infra.example.com
COPY db.reverse.ipv4 /etc/bind/zones/internal/db.10.0.1
COPY db.reverse.ipv6 /etc/bind/zones/internal/db.fd00

COPY hosts.csv /app/hosts.csv
COPY services.csv /app/services.csv

RUN chown -R bind:bind /etc/bind/zones

WORKDIR /app
