FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        gcc \
        libc6-dev \
        make \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /app/src /app/data

COPY Makefile /app/Makefile
COPY flowcore.c /app/src/flowcore.c
COPY flowcore.h /app/src/flowcore.h
COPY flowcal.py /app/flowcal.py
COPY run_calibration.py /app/run_calibration.py
COPY config.toml /app/config.toml
COPY reference_data.sql /app/data/reference_data.sql
