FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    jq \
    make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY corpus.json /tmp/corpus.json
COPY setup_db.py /tmp/setup_db.py
RUN mkdir -p /app/data && python3 /tmp/setup_db.py && rm /tmp/setup_db.py /tmp/corpus.json

COPY queries.json /app/data/queries.json
COPY qrels.json /app/data/qrels.json

COPY engine/ /app/engine/
COPY evaluation/ /app/evaluation/

COPY Makefile /app/Makefile
