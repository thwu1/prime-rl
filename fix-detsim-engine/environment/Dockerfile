FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

COPY app/detsim /opt/task-src/detsim
COPY app/replication /opt/task-src/replication
COPY app/checker /opt/task-src/checker
COPY app/campaign.py /opt/task-src/campaign.py
COPY app/harness.py /opt/task-src/harness.py

RUN mkdir -p /app/results && cp -r /opt/task-src/* /app/

WORKDIR /app
