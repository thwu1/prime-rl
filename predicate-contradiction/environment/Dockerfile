
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY holdings.yaml /app/holdings.yaml
COPY setup_terms.sql /app/setup_terms.sql
COPY spec.md /app/spec.md

RUN sqlite3 /app/terms.db < /app/setup_terms.sql && rm /app/setup_terms.sql

RUN python3 -c "import sqlite3; conn=sqlite3.connect('/app/terms.db'); n=conn.execute('SELECT COUNT(DISTINCT predicate_id) FROM predicate_terms').fetchone()[0]; assert n==32, f'Expected 32 predicates in terms.db, got {n}'"
