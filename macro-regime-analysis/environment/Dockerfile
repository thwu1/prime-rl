FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY data/T10Y2Y.csv /app/data/T10Y2Y.csv
COPY data/FEDFUNDS.csv /app/data/FEDFUNDS.csv
COPY data/UNRATE.csv /app/data/UNRATE.csv
COPY data/CPIAUCSL.csv /app/data/CPIAUCSL.csv
COPY data/M2SL.csv /app/data/M2SL.csv

COPY setup_db.py /tmp/setup_db.py
RUN python3 /tmp/setup_db.py && rm /tmp/setup_db.py

WORKDIR /app
