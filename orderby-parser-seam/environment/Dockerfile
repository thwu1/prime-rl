FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y postgresql postgresql-client python3-pip libpq-dev && rm -rf /var/lib/apt/lists/*

COPY schema.sql /app/schema.sql
COPY queries.sql /app/queries.sql
COPY queries.sql /app/.queries_original.sql
COPY report_spec.md /app/report_spec.md
COPY expected_results.json /app/expected_results.json
COPY bug_taxonomy.md /app/bug_taxonomy.md
COPY init_db.sh /tmp/init_db.sh

RUN chmod +x /tmp/init_db.sh && /tmp/init_db.sh

WORKDIR /app
