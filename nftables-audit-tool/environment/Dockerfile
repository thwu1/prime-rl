FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    nftables \
    jq \
    man-db \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/configs /app/results

COPY configs/workstation.conf /app/configs/workstation.conf
COPY configs/server.conf /app/configs/server.conf
COPY configs/router.conf /app/configs/router.conf
COPY queries.json /app/queries.json
COPY schema.json /app/schema.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 jsonschema==4.23.0
