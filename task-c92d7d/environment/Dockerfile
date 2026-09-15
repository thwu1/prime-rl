
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip git && rm -rf /var/lib/apt/lists/*
RUN pip3 install dbt-duckdb==1.8.4 duckdb==1.5.3

COPY project/ /app/dbt_project/
COPY setup_db.py /tmp/setup_db.py
RUN python3 /tmp/setup_db.py

WORKDIR /app
