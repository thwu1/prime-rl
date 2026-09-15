FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY data/traces.csv /tmp/traces.csv
COPY data/init_db.py /tmp/init_db.py
RUN python3 /tmp/init_db.py && rm /tmp/traces.csv /tmp/init_db.py

COPY data/hw_discovery.xml /app/data/hw_discovery.xml
COPY data/architectures.yaml /app/data/architectures.yaml
COPY data/target_kernels.json /app/data/target_kernels.json
COPY data/incident.log /app/data/incident.log

WORKDIR /app
