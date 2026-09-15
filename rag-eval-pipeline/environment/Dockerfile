FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/qrels /app/data/predictions

COPY data/api_contract.json /app/data/api_contract.json
COPY data/qrels/alpha.tsv /app/data/qrels/alpha.tsv
COPY data/qrels/beta.tsv /app/data/qrels/beta.tsv
COPY data/input.jsonl /app/data/input.jsonl
COPY data/predictions/system_a.jsonl /app/data/predictions/system_a.jsonl
COPY data/predictions/system_b.jsonl /app/data/predictions/system_b.jsonl
COPY data/predictions/system_c.jsonl /app/data/predictions/system_c.jsonl

WORKDIR /app
