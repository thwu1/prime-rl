
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc binutils gdb strace && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/encrypted

COPY cipher_engine.c /tmp/cipher_engine.c
RUN gcc -O2 -s -o /app/cipher_engine /tmp/cipher_engine.c && \
    rm /tmp/cipher_engine.c

COPY gen_challenge.py /tmp/gen_challenge.py
RUN python3 /tmp/gen_challenge.py && rm /tmp/gen_challenge.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
