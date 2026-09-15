FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip gcc libc6-dev sqlite3 libsqlite3-dev && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/legacy /app/data

COPY legacy/rotlib.py /app/legacy/rotlib.py
COPY data/isb_conventions.json /app/data/isb_conventions.json
COPY data/sample_trial.json /app/data/sample_trial.json

