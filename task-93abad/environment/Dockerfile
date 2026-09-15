FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        make \
        python3-pip \
        libc6-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY exp2m1f.h /app/exp2m1f.h
COPY Makefile /app/Makefile

WORKDIR /app
