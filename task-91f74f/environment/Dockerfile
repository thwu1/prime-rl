
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    jq \
    make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY eval_config.toml /app/eval_config.toml
COPY methodology.md /app/methodology.md
COPY Makefile /app/Makefile
COPY broken_evaluate.py /app/evaluate.py
COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py
