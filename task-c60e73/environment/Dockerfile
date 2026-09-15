FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*


COPY ed25519.h /app/ed25519.h
COPY ed25519.c /app/ed25519.c
COPY main.c /app/main.c
COPY Makefile /app/Makefile

WORKDIR /app
