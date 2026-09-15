
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/ns_task /app

COPY ns_iteration.py /opt/ns_task/ns_iteration.py
COPY targets.json /opt/ns_task/targets.json

WORKDIR /app
