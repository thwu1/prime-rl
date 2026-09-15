FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*
RUN pip3 install numpy==1.26.4

COPY mask_base.py /app/mask_base.py
COPY reference.py /app/reference.py
COPY masks.py /app/masks.py
COPY engine.py /app/engine.py
COPY compound_masks.py /app/compound_masks.py
COPY run_checks.py /app/run_checks.py
COPY analysis_schema.json /app/analysis_schema.json
COPY db_schema.sql /app/db_schema.sql

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 jsonschema==4.23.0
