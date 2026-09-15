FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    tshark \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# TCP simulator (working reference implementation)
COPY tcp_sim/ /app/tcp_sim/

# Evaluation harness and scenario definitions
COPY harness.py /app/harness.py
COPY scenarios/ /app/scenarios/

# Generate pcap captures at build time
COPY gen_captures.py /tmp/gen_captures.py
RUN python3 /tmp/gen_captures.py && rm /tmp/gen_captures.py

# Create baseline metrics database at build time
COPY setup_baseline.py /tmp/setup_baseline.py
RUN python3 /tmp/setup_baseline.py && rm /tmp/setup_baseline.py
