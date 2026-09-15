
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip hfst make && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY data/training.tsv /app/data/training.tsv
COPY data/roots.tsv /app/data/roots.tsv
COPY data/test_glosses.txt /app/data/test_glosses.txt

WORKDIR /app
