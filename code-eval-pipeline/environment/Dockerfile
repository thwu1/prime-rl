FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY setup_db.py /tmp/setup_db.py
RUN python3 /tmp/setup_db.py && rm /tmp/setup_db.py

COPY spec.md /app/SPEC.md
COPY harness/ /app/harness/
COPY run_eval.sh /app/run_eval.sh
RUN chmod +x /app/run_eval.sh

WORKDIR /app
