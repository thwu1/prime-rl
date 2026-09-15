FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY init_db.py /app/init_db.py
COPY schema.sql /app/schema.sql
COPY output_schema.json /app/output_schema.json
COPY sources/ /app/sources/

RUN python3 /app/init_db.py && rm /app/init_db.py

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
