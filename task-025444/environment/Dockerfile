
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*
RUN pip3 install pyyaml==6.0.2

COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py

COPY schema.sql /app/schema.sql
COPY output_schema.json /app/output_schema.json
COPY audit_query.sql /app/audit_query.sql
COPY benchmark_score_ref.java /app/reference/BenchmarkScore.java
COPY reference_scorecard.json /app/reference_scorecard.json
COPY report_template.jq /app/report_template.jq
COPY pipeline /app/pipeline
COPY run_pipeline.sh /app/run_pipeline.sh
RUN chmod +x /app/run_pipeline.sh

WORKDIR /app
