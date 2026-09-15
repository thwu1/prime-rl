FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip jq sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/app-src /app

COPY app/models.py /opt/app-src/models.py
COPY app/engine.py /opt/app-src/engine.py
COPY app/journal.py /opt/app-src/journal.py
COPY app/snapshot.py /opt/app-src/snapshot.py
COPY app/replay.py /opt/app-src/replay.py
COPY app/market_data.py /opt/app-src/market_data.py
COPY app/SPEC.md /opt/app-src/SPEC.md
COPY app/production.jsonl /opt/app-src/production.jsonl

RUN cp /opt/app-src/*.py /app/ && cp /opt/app-src/SPEC.md /app/ && cp /opt/app-src/production.jsonl /app/

WORKDIR /app
