FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install duckdb==1.1.3 pyyaml==6.0.2

RUN mkdir -p /app

COPY init_db.py /tmp/init_db.py
COPY semantic_model.yaml /app/semantic_model.yaml
COPY query_requests.json /app/query_requests.json

RUN python3 /tmp/init_db.py && rm /tmp/init_db.py

WORKDIR /app
