FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/cache

COPY schema.md /app/schema.md
COPY spec.md /app/spec.md
COPY reference.md /app/reference.md
COPY calculator.py /app/calculator.py
COPY queries.json /app/queries.json
COPY cache/ /app/cache/

WORKDIR /app
