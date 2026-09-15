FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y postgresql postgresql-client python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY init.sql /tmp/init.sql
COPY init.sql /app/init.sql
COPY knowledge_base.jsonl /app/knowledge_base.jsonl
COPY setup_db.sh /tmp/setup_db.sh

RUN chmod +x /tmp/setup_db.sh && /tmp/setup_db.sh

WORKDIR /app
