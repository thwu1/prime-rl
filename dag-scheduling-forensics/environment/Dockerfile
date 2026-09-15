FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip jq graphviz sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/dags

COPY config.json /app/config.json
COPY expected_schema.json /app/expected_schema.json
COPY execution_log.jsonl /app/execution_log.jsonl
COPY scheduler_events.jsonl /app/scheduler_events.jsonl
COPY dags/ /app/dags/

WORKDIR /app
