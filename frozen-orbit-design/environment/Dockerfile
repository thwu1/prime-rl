FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY create_db.py /tmp/create_db.py
RUN python3 /tmp/create_db.py && rm /tmp/create_db.py

COPY validate_output.jq /app/validate_output.jq

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
