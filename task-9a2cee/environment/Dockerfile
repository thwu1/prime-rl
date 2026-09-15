FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip jq openssl && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY setup_packages.py /tmp/setup_packages.py
COPY schema.json /app/schema.json

RUN python3 /tmp/setup_packages.py && rm /tmp/setup_packages.py

WORKDIR /app
