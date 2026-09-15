FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y sqlite3 python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

ENV TZ=UTC

RUN mkdir -p /app

COPY setup_db.py /app/setup_db.py
RUN python3 /app/setup_db.py && rm /app/setup_db.py

WORKDIR /app
