
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y \
    tshark \
    tcpdump \
    python3-pip \
    python3-scapy \
    jq \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
COPY generate_pcap.py /tmp/generate_pcap.py
RUN python3 /tmp/generate_pcap.py && rm /tmp/generate_pcap.py

WORKDIR /app
