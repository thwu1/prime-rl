FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY generate_all.py /tmp/generate_all.py
RUN python3 /tmp/generate_all.py && rm /tmp/generate_all.py

WORKDIR /app
