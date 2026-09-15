FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-pip \
        hashcat \
        john \
        jq \
        && rm -rf /var/lib/apt/lists/*

COPY app/loot/ /app/loot/
COPY app/config/ /app/config/
COPY app/wordlists/ /app/wordlists/

RUN mkdir -p /app/report

WORKDIR /app
