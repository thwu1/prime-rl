
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/docs /app/pipeline /app/output

COPY app/data/results.json /tmp/init_data.json
COPY app/data/init_db.py /tmp/init_db.py
RUN python3 /tmp/init_db.py && rm /tmp/init_data.json /tmp/init_db.py

COPY app/data/labeled_patches.json /app/data/labeled_patches.json

COPY app/docs/metric_analysis.md /app/docs/metric_analysis.md
COPY app/docs/output_schema.json /app/docs/output_schema.json

COPY app/extract_data.sh /app/extract_data.sh
RUN chmod +x /app/extract_data.sh

COPY app/run.sh /app/run.sh
RUN chmod +x /app/run.sh

COPY app/run.py /app/run.py

COPY app/pipeline/__init__.py /app/pipeline/__init__.py
COPY app/pipeline/metrics.py /app/pipeline/metrics.py
COPY app/pipeline/evaluator.py /app/pipeline/evaluator.py
COPY app/pipeline/hack_detector.py /app/pipeline/hack_detector.py
COPY app/pipeline/ranking.py /app/pipeline/ranking.py

WORKDIR /app
