FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc make sqlite3 libsqlite3-dev && \
    rm -rf /var/lib/apt/lists/*

COPY generate_corpus.py /app/generate_corpus.py
COPY bm25.py /app/bm25.py
COPY reference.py /app/reference.py
COPY search_engine_skeleton.py /app/search_engine.py
COPY scorer_skeleton.c /app/scorer.c

RUN python3 /app/generate_corpus.py

WORKDIR /app

