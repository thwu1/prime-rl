FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data
COPY data/pr-data.csv /app/data/pr-data.csv
COPY data/gr-data.csv /app/data/gr-data.csv
COPY data/py-data.csv /app/data/py-data.csv
COPY data/odr-tests.csv /app/data/odr-tests.csv
COPY data/tic-fic-data.csv /app/data/tic-fic-data.csv
COPY data/tso-iso-rates.csv /app/data/tso-iso-rates.csv

WORKDIR /app
