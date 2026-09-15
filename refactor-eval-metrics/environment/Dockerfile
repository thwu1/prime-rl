
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    jq \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /app/pipeline /app/results /app/reference

COPY methodology.md /app/METHODOLOGY.md
COPY evaluation_models.py /app/reference/evaluation_models.py
COPY generate_data.py /tmp/generate_data.py

RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py
