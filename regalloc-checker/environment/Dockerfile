FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    graphviz \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY spec.md /app/spec.md
COPY test_programs/ /app/_staging/
COPY create_db.py /app/_staging/create_db.py

RUN python3 /app/_staging/create_db.py && rm -rf /app/_staging

RUN mkdir -p /app/output
