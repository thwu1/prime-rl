FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN pip3 install pyyaml==6.0.2

COPY partitions.py /app/partitions.py
COPY mappings.py /app/mappings.py
COPY reconciler.py /app/reconciler.py
COPY io_manager.py /app/io_manager.py
COPY db_store.py /app/db_store.py
COPY config_loader.py /app/config_loader.py
COPY pipeline.yaml /app/pipeline.yaml
COPY events.jsonl /app/events.jsonl
COPY costs.yaml /app/costs.yaml
COPY init_db.py /app/init_db.py

RUN python3 /app/init_db.py && rm /app/init_db.py

WORKDIR /app
