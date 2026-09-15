
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        jq \
        sqlite3 \
        graphviz \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY network/configs/ /app/network/configs/
COPY network/topology.json /app/network/topology.json
COPY network/requirements.json /app/network/requirements.json
COPY network/design.sql /tmp/design.sql

RUN sqlite3 /app/network/design.db < /tmp/design.sql && rm /tmp/design.sql

COPY dnac/dnac_api.py /app/dnac/dnac_api.py
COPY dnac/start.sh /app/dnac/start.sh
RUN chmod +x /app/dnac/start.sh

RUN mkdir -p /app/output /var/log

WORKDIR /app
