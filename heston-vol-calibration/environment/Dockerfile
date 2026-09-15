FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY create_db.py /tmp/create_db.py
RUN python3 /tmp/create_db.py && rm /tmp/create_db.py

WORKDIR /app
