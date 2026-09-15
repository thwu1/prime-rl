FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/pricing_task

COPY setup.sql /tmp/setup.sql
RUN sqlite3 /opt/pricing_task/supermarket.db < /tmp/setup.sql && rm /tmp/setup.sql

COPY app/ /opt/pricing_task/

WORKDIR /app
