
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN echo "wireshark-common wireshark-common/install-setuid boolean false" | debconf-set-selections && \
    DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y python3 python3-pip tshark tcpdump nftables && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/captures

COPY generate_captures.py /tmp/generate_captures.py
RUN python3 /tmp/generate_captures.py && rm /tmp/generate_captures.py

COPY incident.md /app/incident.md
COPY schema.json /app/schema.json

WORKDIR /app
