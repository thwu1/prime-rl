FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 xxd file binwalk yara ssdeep && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY setup_evidence.py /tmp/setup_evidence.py
RUN python3 /tmp/setup_evidence.py && rm /tmp/setup_evidence.py

WORKDIR /app
