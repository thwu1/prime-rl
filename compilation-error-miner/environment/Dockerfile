FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    build-essential \
    patch \
    && rm -rf /var/lib/apt/lists/*

COPY project/ /app/project/
COPY ci_logs/ /app/ci_logs/
COPY patches/ /app/patches/

RUN mkdir -p /app/output

WORKDIR /app
