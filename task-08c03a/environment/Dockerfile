FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN pip3 install PyYAML==6.0.2

RUN mkdir -p /app/pipeline

COPY pipeline/__init__.py /app/pipeline/__init__.py
COPY pipeline/loader.py /app/pipeline/loader.py
COPY pipeline/multipart.py /app/pipeline/multipart.py
COPY pipeline/reconciler.py /app/pipeline/reconciler.py
COPY pipeline/optimizer.py /app/pipeline/optimizer.py
COPY pipeline/planner.py /app/pipeline/planner.py
COPY pipeline.yaml /app/pipeline.yaml
COPY cost_config.yaml /app/cost_config.yaml
COPY validate.py /app/validate.py
COPY init_db.sql /tmp/init_db.sql
RUN sqlite3 /app/partitions.db < /tmp/init_db.sql && rm /tmp/init_db.sql

WORKDIR /app
