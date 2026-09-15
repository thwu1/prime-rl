FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    openssl \
    sqlite3 \
    pari-gp \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/certs

COPY vinaigrette.py /app/vinaigrette.py
COPY public_key.txt /tmp/public_key_raw.txt
COPY setup_env.py /tmp/setup_env.py

RUN python3 /tmp/setup_env.py && rm /tmp/setup_env.py && rm -f /tmp/public_key_raw.txt

WORKDIR /app
