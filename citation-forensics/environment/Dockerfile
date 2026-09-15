FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq recutils && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY setup_db.py /tmp/setup_db.py
RUN python3 /tmp/setup_db.py && rm /tmp/setup_db.py

COPY supplementary_responses.jsonl /app/data/supplementary_responses.jsonl
COPY court_hierarchy.rec /app/data/court_hierarchy.rec
COPY error_config.json /app/data/error_config.json
COPY eval_config.yaml /app/data/eval_config.yaml
COPY methodology.md /app/data/methodology.md

WORKDIR /app
