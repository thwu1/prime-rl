FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY capture.ndpi /app/data/ndpi_flows.txt
COPY threat_intel.json /app/data/threat_intel.json
COPY schema.json /app/schema.json

WORKDIR /app
