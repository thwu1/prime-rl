FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/clinical_eval

COPY data/gold_brat /app/data/gold_brat
COPY data/system_brat /app/data/system_brat
COPY data/gold_xml /app/data/gold_xml
COPY data/system_xml /app/data/system_xml
COPY data/spec.md /app/data/spec.md

WORKDIR /app
