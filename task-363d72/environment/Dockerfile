FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 jq graphviz && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/ad_data

COPY generate_data.py /tmp/generate_data.py
COPY engagement_brief.txt /app/ad_data/engagement_brief.txt

RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app
