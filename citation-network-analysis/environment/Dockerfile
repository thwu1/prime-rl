
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/corpus

COPY corpus/opinion_001.txt /app/corpus/opinion_001.txt
COPY corpus/opinion_002.txt /app/corpus/opinion_002.txt
COPY corpus/opinion_003.txt /app/corpus/opinion_003.txt
COPY corpus/opinion_004.txt /app/corpus/opinion_004.txt
COPY corpus/opinion_005.txt /app/corpus/opinion_005.txt
COPY previous_audit.json /app/previous_audit.json

WORKDIR /app
