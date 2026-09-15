
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    openssl \
    sqlite3 \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/artifacts

COPY setup_challenge.py /tmp/setup_challenge.py
RUN python3 /tmp/setup_challenge.py && rm /tmp/setup_challenge.py

WORKDIR /app
