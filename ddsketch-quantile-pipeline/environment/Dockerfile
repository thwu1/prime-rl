FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip python3-yaml sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/pipeline /app/data /app/expected /app/output /app/schema

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

COPY output_schema.json /app/schema/output_schema.json

COPY sketch_engine.py /app/pipeline/sketch_engine.py
COPY data_loader.py /app/pipeline/data_loader.py
COPY aggregator.py /app/pipeline/aggregator.py
COPY reporter.py /app/pipeline/reporter.py
COPY run_pipeline.py /app/pipeline/run_pipeline.py

WORKDIR /app
