FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip python3 sqlite3 && \
    rm -rf /var/lib/apt/lists/*

COPY app/ /app/

RUN python3 /app/setup_db.py && \
    rm -f /app/setup_db.py && \
    rm -f /app/data/v_*.csv

RUN mkdir -p /app/output

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
