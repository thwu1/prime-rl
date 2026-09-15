FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY seed_data.py /app/seed_data.py
RUN python3 /app/seed_data.py && rm /app/seed_data.py

WORKDIR /app
