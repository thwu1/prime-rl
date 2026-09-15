FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip rustc cargo gcc && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data
COPY data/months.tsv /app/data/months.tsv
COPY data/prefixes.tsv /app/data/prefixes.tsv
COPY data/words_a.tsv /app/data/words_a.tsv
COPY data/words_b.tsv /app/data/words_b.tsv
COPY data/reference.json /app/data/reference.json

WORKDIR /app
