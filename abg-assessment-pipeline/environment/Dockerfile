FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY references/ /app/references/
COPY baseline_engine.py /app/baseline_engine.py
COPY clinical_params.sql /app/clinical_params.sql
COPY init_params.py /app/init_params.py
COPY calibration/ /app/calibration/
COPY schema.json /app/schema.json
