FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    jq \
    gawk \
    && rm -rf /var/lib/apt/lists/*

COPY analyze.sh /app/analyze.sh
COPY lib/ /app/lib/
COPY data/ /app/data/

RUN chmod +x /app/analyze.sh

