
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip sqlite3 postgresql postgresql-client jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/queries /app/fixed_queries

COPY setup_db.py /app/setup_db.py
COPY pg_schema.sql /app/pg_schema.sql
COPY setup_pg.sh /app/setup_pg.sh
COPY knowledge_base.md /app/knowledge_base.md
COPY queries/ /app/queries/

RUN python3 /app/setup_db.py

RUN chmod +x /app/setup_pg.sh && bash /app/setup_pg.sh

WORKDIR /app
