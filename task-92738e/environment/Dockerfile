
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 openssl xxd && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/keys /app/sigs /app/output

COPY data.json /tmp/data.json
COPY setup_corpus.py /tmp/setup_corpus.py
RUN python3 /tmp/setup_corpus.py && rm /tmp/data.json /tmp/setup_corpus.py

WORKDIR /app
