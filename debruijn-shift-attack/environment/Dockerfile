FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y \
    python3 python3-pip \
    tshark socat netcat-openbsd \
    xxd openssl \
    && rm -rf /var/lib/apt/lists/*

COPY gen_config.py /tmp/gen_config.py
COPY receiver.py /app/receiver.py

RUN mkdir -p /app/sequences && \
    python3 /tmp/gen_config.py /app && \
    rm /tmp/gen_config.py

WORKDIR /app
