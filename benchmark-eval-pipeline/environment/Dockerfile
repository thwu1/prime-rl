FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4

RUN mkdir -p /app

COPY spec.md /app/SPEC.md
COPY evaluator_stub.py /app/evaluator.py
COPY config.toml /app/config.toml

WORKDIR /app
