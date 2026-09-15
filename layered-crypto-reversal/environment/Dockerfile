FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    binutils \
    tshark \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY crypto_engine.c /tmp/crypto_engine.c
RUN gcc -shared -fPIC -O2 -o /app/crypto_engine.so /tmp/crypto_engine.c && \
    strip /app/crypto_engine.so && \
    rm /tmp/crypto_engine.c

COPY setup_challenge.py /tmp/setup_challenge.py
RUN python3 /tmp/setup_challenge.py && rm /tmp/setup_challenge.py

COPY protocol.py /app/protocol.py
COPY PROTOCOL_SPEC.md /app/PROTOCOL_SPEC.md

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
