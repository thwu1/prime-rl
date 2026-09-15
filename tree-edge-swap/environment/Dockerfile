FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 graphviz jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY setup_environment.py /tmp/setup_environment.py
RUN python3 /tmp/setup_environment.py && rm /tmp/setup_environment.py

WORKDIR /app
