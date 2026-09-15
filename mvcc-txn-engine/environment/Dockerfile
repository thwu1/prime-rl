FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 jq socat && rm -rf /var/lib/apt/lists/*

COPY app/mvcc_store.py /app/mvcc_store.py
COPY app/mvcc_server.py /app/mvcc_server.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
