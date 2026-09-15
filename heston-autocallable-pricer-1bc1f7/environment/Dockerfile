FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    make \
    jq \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/legacy /app/data /logs/verifier

COPY legacy/pricer_v1.py /app/legacy/pricer_v1.py
COPY data/heston_reference.csv /app/data/heston_reference.csv
COPY data/termsheet.yaml /app/data/termsheet.yaml
COPY data/correlation_sample.json /app/data/correlation_sample.json
COPY data/note_config.json /app/data/note_config.json

