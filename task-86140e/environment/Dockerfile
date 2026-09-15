FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/plans /app/tools

COPY plans/ /app/data/plans/

COPY setup_db.py /tmp/setup_db.py
RUN python3 /tmp/setup_db.py && rm /tmp/setup_db.py

COPY plan-extract /app/tools/plan-extract
RUN chmod +x /app/tools/plan-extract

ENV PATH="/app/tools:${PATH}"

COPY schema.json /app/schema.json

WORKDIR /app
