FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data /app

COPY app_data/regression_export.csv /data/regression_export.csv
COPY app_data/patch_metadata.jsonl /data/patch_metadata.jsonl
COPY app_data/output_schema.json /data/output_schema.json
COPY app_data/README.txt /data/README.txt

WORKDIR /app
