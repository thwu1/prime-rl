FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip python3 jq sqlite3 && rm -rf /var/lib/apt/lists/*

COPY app/ /app/
COPY scripts/create_terminology_db.py /tmp/create_terminology_db.py
RUN python3 /tmp/create_terminology_db.py && rm /tmp/create_terminology_db.py && rm /app/terminology/valueset_bundle.json && rm /app/value_sets.json

WORKDIR /app
