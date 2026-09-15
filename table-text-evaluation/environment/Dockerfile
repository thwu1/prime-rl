FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY tables.json /app/data/tables.json
COPY texts.json /app/data/texts.json
COPY pairs.csv /app/data/pairs.csv
COPY pipeline_broken.py /app/pipeline.py
COPY SPEC.md /app/SPEC.md

WORKDIR /app
