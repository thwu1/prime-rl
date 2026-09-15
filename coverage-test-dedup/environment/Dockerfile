FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data

COPY generate_db.py /tmp/generate_db.py
RUN python3 /tmp/generate_db.py && rm /tmp/generate_db.py

WORKDIR /app
