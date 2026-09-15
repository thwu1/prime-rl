FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq make && rm -rf /var/lib/apt/lists/*

COPY data_generator.py /app/data_generator.py
RUN python3 /app/data_generator.py

COPY config.json /app/config.json
COPY schema.sql /app/schema.sql

RUN mkdir -p /app/pipeline

WORKDIR /app
