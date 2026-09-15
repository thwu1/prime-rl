FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    tshark \
    jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY vpn_routes.csv /app/vpn_routes.csv
COPY queries.json /app/queries.json
COPY configs/ /app/configs/

COPY setup_db.py /tmp/setup_db.py
COPY generate_pcaps.py /tmp/generate_pcaps.py
RUN python3 /tmp/setup_db.py && python3 /tmp/generate_pcaps.py && rm /tmp/setup_db.py /tmp/generate_pcaps.py
