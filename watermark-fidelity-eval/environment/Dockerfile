FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/attacks

COPY data/corpus.jsonl /app/data/corpus.jsonl
COPY data/synonyms.json /app/data/synonyms.json
COPY attacks/attack.py /app/attacks/attack.py

RUN chmod +x /app/attacks/attack.py

WORKDIR /app
