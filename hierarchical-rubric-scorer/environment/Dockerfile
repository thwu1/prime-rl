FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PYTHONPATH=/app


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

RUN mkdir -p /app/data /app/output /app/pipeline

COPY rubric.json /app/data/rubric.json
COPY judgments.jsonl /app/data/judgments.jsonl
COPY pipeline_init.py /app/pipeline/__init__.py
COPY pipeline_main.py /app/pipeline/main.py
COPY pipeline_loader.py /app/pipeline/loader.py
COPY pipeline_aggregator.py /app/pipeline/aggregator.py
COPY pipeline_scorer.py /app/pipeline/scorer.py
COPY pipeline_metrics.py /app/pipeline/metrics.py

WORKDIR /app
