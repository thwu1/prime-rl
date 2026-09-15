FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip python3-dev sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY generate_samples.py /app/generate_samples.py
COPY task_spec.json /app/task_spec.json

RUN python3 /app/generate_samples.py

WORKDIR /app
