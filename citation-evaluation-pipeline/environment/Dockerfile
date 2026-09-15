FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    jq \
    xmlstarlet \
    libxml2-utils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY data/instances.jsonl /tmp/instances.jsonl
COPY data/responses.jsonl /tmp/responses.jsonl
COPY create_db.py /tmp/create_db.py

RUN python3 /tmp/create_db.py && rm -f /tmp/create_db.py /tmp/instances.jsonl /tmp/responses.jsonl

COPY ground_truth_manifest.jsonl /app/ground_truth_manifest.jsonl
COPY citation_authority.xml /app/citation_authority.xml
COPY scoring_config.yaml /app/scoring_config.yaml
COPY scoring_overrides.json /app/scoring_overrides.json
COPY evaluation_methodology.md /app/evaluation_methodology.md
COPY audit_notes.md /app/audit_notes.md
COPY evaluate.py /app/evaluate.py

WORKDIR /app
