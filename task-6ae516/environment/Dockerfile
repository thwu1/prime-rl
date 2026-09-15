FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/architectures /app/profiling

COPY app/architectures/sm80.json /app/architectures/sm80.json
COPY app/architectures/sm90.json /app/architectures/sm90.json
COPY app/profiling/ncu_sm80.csv /app/profiling/ncu_sm80.csv
COPY app/profiling/ncu_sm90.csv /app/profiling/ncu_sm90.csv
COPY app/report_schema.json /app/report_schema.json
COPY app/setup_db.py /tmp/setup_db.py

RUN python3 /tmp/setup_db.py && rm /tmp/setup_db.py

WORKDIR /app
