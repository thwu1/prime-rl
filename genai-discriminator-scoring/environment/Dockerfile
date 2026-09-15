
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip python3-dev jq sqlite3 make && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/predictions /app/pipeline /app/reference /app/output

COPY data/ground_truth.json /app/data/ground_truth.json
COPY data/predictions/disc_reliable_set1.json /app/data/predictions/disc_reliable_set1.json
COPY data/predictions/disc_reliable_set2.json /app/data/predictions/disc_reliable_set2.json
COPY data/predictions/disc_biased_set1.json /app/data/predictions/disc_biased_set1.json
COPY data/predictions/disc_uncalibrated_set1.json /app/data/predictions/disc_uncalibrated_set1.json
COPY data/predictions/disc_malformed_set1.json /app/data/predictions/disc_malformed_set1.json
COPY data/predictions/disc_degenerate_set3.json /app/data/predictions/disc_degenerate_set3.json

COPY nist_spec.md /app/nist_spec.md

COPY pipeline/Makefile /app/pipeline/Makefile
COPY pipeline/schema.sql /app/pipeline/schema.sql
COPY pipeline/ingest.sh /app/pipeline/ingest.sh
COPY pipeline/validate.sh /app/pipeline/validate.sh
COPY pipeline/compute.py /app/pipeline/compute.py
COPY pipeline/config.json /app/pipeline/config.json
COPY pipeline/rank.sql /app/pipeline/rank.sql
RUN chmod +x /app/pipeline/ingest.sh /app/pipeline/validate.sh /app/pipeline/compute.py

COPY reference/reference_output.json /app/reference/reference_output.json

WORKDIR /app
