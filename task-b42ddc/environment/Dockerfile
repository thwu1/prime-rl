
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip openssl jq sqlite3 && \
    rm -rf /var/lib/apt/lists/*

COPY data/ /app/
COPY setup_crypto.py /tmp/setup_crypto.py
RUN python3 /tmp/setup_crypto.py && rm /tmp/setup_crypto.py

WORKDIR /app
