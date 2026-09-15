
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    nginx \
    tshark \
    curl \
    socat \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY app/ /app/
COPY setup/gen_pcap.py /tmp/gen_pcap.py
RUN python3 /tmp/gen_pcap.py && rm /tmp/gen_pcap.py

ENV PYTHONPATH=/app
WORKDIR /app
