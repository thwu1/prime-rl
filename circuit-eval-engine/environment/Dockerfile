
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip sqlite3 jq gzip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY simulator.py /app/simulator.py
COPY pipeline.py /app/pipeline.py
COPY methods_draft.md /app/methods_draft.md

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py
