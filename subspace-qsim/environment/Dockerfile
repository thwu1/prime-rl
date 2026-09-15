FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 xxd jq && \
    rm -rf /var/lib/apt/lists/*

COPY create_db.py /tmp/create_db.py
COPY circuit.json /tmp/circuit.json
COPY observables.toml /app/observables.toml

RUN python3 /tmp/create_db.py /tmp/circuit.json /app/circuit.db /app/params.bin && \
    rm /tmp/create_db.py /tmp/circuit.json

WORKDIR /app
