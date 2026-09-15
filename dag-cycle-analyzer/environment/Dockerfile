FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY dags/ /app/dags/
COPY config/ /app/config/
COPY create_metadata.py /tmp/create_metadata.py
RUN python3 /tmp/create_metadata.py && rm /tmp/create_metadata.py

WORKDIR /app
