
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip make && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install bandit==1.7.7 -q

COPY app/ /app/

RUN mkdir -p /app/data/loot /app/output /app/patched /app/exploits /app/scanner

WORKDIR /app
