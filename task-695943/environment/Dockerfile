
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip build-essential sqlite3 binutils xxd file && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY build_task.py /tmp/build_task.py
RUN python3 /tmp/build_task.py && rm /tmp/build_task.py

WORKDIR /app
