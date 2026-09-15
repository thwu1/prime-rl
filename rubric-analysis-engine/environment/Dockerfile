FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/legacy /app/docs /app/config /app/output

COPY setup_db.py /tmp/setup_db.py
RUN python3 /tmp/setup_db.py && rm /tmp/setup_db.py

COPY legacy_scorer.py /app/legacy/scorer.py
COPY pipeline.sh /app/legacy/pipeline.sh
RUN chmod +x /app/legacy/pipeline.sh
COPY scoring_notes.md /app/docs/scoring_notes.md
COPY policy.yaml /app/config/policy.yaml

WORKDIR /app
