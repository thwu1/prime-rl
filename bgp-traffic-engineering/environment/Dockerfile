FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    frr \
    iproute2 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/configs /app/logs

COPY topology.txt /app/topology.txt
COPY configs/r1.conf /app/configs/r1.conf
COPY configs/r2.conf /app/configs/r2.conf
COPY configs/r3.conf /app/configs/r3.conf
COPY configs/r4.conf /app/configs/r4.conf
COPY logs/r1_bgpd.log /app/logs/r1_bgpd.log
COPY logs/r2_bgpd.log /app/logs/r2_bgpd.log
COPY logs/r3_bgpd.log /app/logs/r3_bgpd.log
COPY logs/r4_bgpd.log /app/logs/r4_bgpd.log

WORKDIR /app
