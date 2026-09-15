
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    iproute2 \
    nftables \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/captures

COPY captures/eth0_qdisc.txt /app/captures/eth0_qdisc.txt
COPY captures/eth0_class.txt /app/captures/eth0_class.txt
COPY captures/eth0_filter.txt /app/captures/eth0_filter.txt
COPY captures/eth1_qdisc.txt /app/captures/eth1_qdisc.txt
COPY captures/eth1_class.txt /app/captures/eth1_class.txt
COPY captures/eth1_filter.txt /app/captures/eth1_filter.txt
COPY captures/nft_ruleset.txt /app/captures/nft_ruleset.txt
COPY captures/ip_link.txt /app/captures/ip_link.txt
COPY sla_requirements.json /app/sla_requirements.json

WORKDIR /app
