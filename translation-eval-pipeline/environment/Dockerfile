FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip jq make && rm -rf /var/lib/apt/lists/*

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py \
    && test -f /data/benchmark/manifest.json \
    && test -d /data/benchmark/projects/proj_01 \
    && test -d /data/benchmark/projects/proj_10 \
    && rm /tmp/generate_data.py

WORKDIR /app

COPY pipeline_config.json /app/pipeline_config.json
COPY output_schema.json /app/output_schema.json
COPY Makefile /app/Makefile
COPY pipeline/ /app/pipeline/
COPY evaluate.sh /app/evaluate.sh
RUN chmod +x /app/evaluate.sh
