FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

COPY tools/ /app/tools/
RUN chmod +x /app/tools/*

COPY repo/ /app/repo/
COPY setup_registry.sql /tmp/setup_registry.sql
RUN sqlite3 /app/registry.db < /tmp/setup_registry.sql && rm /tmp/setup_registry.sql

COPY baseline_report.json /app/baseline_report.json

WORKDIR /app
