FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN pip3 install duckdb==1.1.3

RUN mkdir -p /app/src /app/data /app/docs /app/output /app/intermediate

COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py

COPY docs/spec.md /app/docs/spec.md
COPY src/pipeline.py /app/src/pipeline.py
COPY src/extract.sql /app/src/extract.sql
COPY src/transform.py /app/src/transform.py
COPY src/assemble.jq /app/src/assemble.jq

WORKDIR /app
