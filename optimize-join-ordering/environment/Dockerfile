FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install duckdb==1.0.0

COPY task_data/ /opt/task_data/
COPY setup_db.py /tmp/setup_db.py

WORKDIR /app
RUN python3 /tmp/setup_db.py && rm /tmp/setup_db.py

