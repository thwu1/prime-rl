FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 jq make && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install pyyaml==6.0.2

COPY app/ /app/

RUN python3 /app/init_db.py && rm /app/init_db.py

RUN mkdir -p /app/output /app/intermediate

WORKDIR /app
