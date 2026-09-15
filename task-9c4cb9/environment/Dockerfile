
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    xxd \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/stations /app/tools /app/docs

COPY gen_stations.py /tmp/gen_stations.py
RUN python3 /tmp/gen_stations.py && rm /tmp/gen_stations.py

COPY msg_check /app/tools/msg_check
RUN chmod +x /app/tools/msg_check

COPY stations.json /app/stations/stations.json
COPY mode_s_reference.txt /app/docs/mode_s_reference.txt
COPY db_schema.sql /app/docs/db_schema.sql

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
