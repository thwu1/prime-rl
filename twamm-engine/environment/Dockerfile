FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc libc6-dev make sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/lib /app/data /app/docs

COPY app/lib/cpamm.h /app/lib/cpamm.h
COPY app/lib/cpamm.c /app/lib/cpamm.c
COPY app/lib/Makefile /app/lib/Makefile
COPY app/data/init.sql /app/data/init.sql
COPY app/docs/twamm_mechanism.md /app/docs/twamm_mechanism.md
COPY app/docs/virtual_trade_notes.md /app/docs/virtual_trade_notes.md

