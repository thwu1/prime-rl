FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install sqlite-utils==3.39

RUN mkdir -p /app/data
COPY registry.csv /app/data/registry.csv
COPY downloads.jsonl /app/data/downloads.jsonl
COPY dependencies.json /app/data/dependencies.json

WORKDIR /app
