FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    openssl \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY setup_challenge.py /tmp/setup_challenge.py
RUN python3 /tmp/setup_challenge.py && rm /tmp/setup_challenge.py

WORKDIR /app
