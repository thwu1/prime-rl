FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/tools

COPY bm25_search.py /app/tools/bm25_search.py
COPY evaluate.py /app/tools/evaluate.py
COPY setup_task.py /tmp/setup_task.py
RUN python3 /tmp/setup_task.py && rm /tmp/setup_task.py

WORKDIR /app
