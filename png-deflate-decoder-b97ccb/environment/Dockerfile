FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y gcc make python3-pip && \
    rm -rf /var/lib/apt/lists/*


COPY decode_png.c /app/decode_png.c
COPY decode_png.h /app/decode_png.h
COPY Makefile /app/Makefile

WORKDIR /app
