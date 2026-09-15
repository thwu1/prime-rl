FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY generate_data.py /app/generate_data.py
COPY sketch.py /app/sketch.py
COPY pipeline.py /app/pipeline.py
COPY sla_config.json /app/sla_config.json

RUN python3 /app/generate_data.py

WORKDIR /app
