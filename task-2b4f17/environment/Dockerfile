FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install cryptography==44.0.0

COPY setup_firmware.py /tmp/setup_firmware.py
COPY key_mgmt.py /tmp/key_mgmt.py
RUN python3 /tmp/setup_firmware.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    openssl \
    file \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install cryptography==44.0.0

COPY --from=builder /app/ /app/

RUN openssl genrsa -out /app/.hardened_privkey.pem 2048 2>/dev/null && \
    openssl rsa -in /app/.hardened_privkey.pem -pubout -out /app/hardened_pubkey.pem 2>/dev/null && \
    test -f /app/hardened_pubkey.pem && test -f /app/.hardened_privkey.pem

WORKDIR /app
