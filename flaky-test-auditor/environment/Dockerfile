FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /app/reconciler /app/schema

COPY setup_db.py /tmp/setup_db.py
RUN python3 /tmp/setup_db.py && rm /tmp/setup_db.py

COPY engine.py /app/reconciler/engine.py
RUN touch /app/reconciler/__init__.py

COPY report_schema.json /app/schema/report_schema.json
COPY validate.sh /app/validate.sh
RUN chmod +x /app/validate.sh
