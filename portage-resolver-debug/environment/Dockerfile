FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 graphviz jq && \
    rm -rf /var/lib/apt/lists/*

COPY app /opt/task_src

RUN cd /opt/task_src && \
    sqlite3 packages.db < schema.sql && \
    sqlite3 packages.db < seed_data.sql

RUN cp -r /opt/task_src /app

WORKDIR /app

