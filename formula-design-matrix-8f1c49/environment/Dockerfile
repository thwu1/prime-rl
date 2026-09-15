FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    make \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/reference
COPY app/Makefile /app/Makefile
COPY app/cli.py /app/cli.py
COPY app/validate.py /app/validate.py
COPY app/init.sql /app/init.sql
COPY app/reference /app/reference

WORKDIR /app

