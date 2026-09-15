FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app /data

COPY setup_env.py /tmp/setup_env.py
RUN python3 /tmp/setup_env.py && rm /tmp/setup_env.py

WORKDIR /app
