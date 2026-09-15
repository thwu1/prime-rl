FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential libssl-dev pkg-config python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY buggy_acvp_module.c /app/acvp_module.c
RUN gcc -O2 -o /app/acvp_module /app/acvp_module.c -lcrypto

COPY check_module.py /app/check_module.py
RUN chmod +x /app/check_module.py

COPY protocol_ref.md /app/PROTOCOL.md
