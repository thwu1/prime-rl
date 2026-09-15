FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    make \
    python3-pip \
    python3-setuptools \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY gsw_check_data.h /app/gsw_check_data.h
COPY gsw_pipeline.h /app/gsw_pipeline.h
COPY gsw_pipeline.c /app/gsw_pipeline.c
COPY main.c /app/main.c
COPY Makefile /app/Makefile

WORKDIR /app

