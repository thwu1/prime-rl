FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    build-essential \
    python3-dev \
    sqlite3 \
    make \
    && rm -rf /var/lib/apt/lists/*

COPY data/meta.yaml /app/data/meta.yaml
COPY data/generate_dataset.py /app/data/generate_dataset.py
COPY pipeline/evaluator.py /app/pipeline/evaluator.py
COPY pipeline/extract.py /app/pipeline/extract.py
COPY pipeline/notes.txt /app/pipeline/notes.txt
COPY Makefile /app/Makefile

WORKDIR /app
