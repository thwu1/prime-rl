FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/config

COPY config/network /app/config/network
COPY config/firewall /app/config/firewall
COPY config/dhcp /app/config/dhcp
COPY config/wireless /app/config/wireless
COPY change_request.md /app/change_request.md
COPY admin_notes.md /app/admin_notes.md

WORKDIR /app
