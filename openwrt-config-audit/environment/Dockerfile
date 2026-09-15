FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/etc/config /app/etc/stubby

COPY configs/network /app/etc/config/network
COPY configs/firewall /app/etc/config/firewall
COPY configs/dhcp /app/etc/config/dhcp
COPY configs/stubby.yml /app/etc/stubby/stubby.yml
COPY configs/network_design.txt /app/network_design.txt

WORKDIR /app
