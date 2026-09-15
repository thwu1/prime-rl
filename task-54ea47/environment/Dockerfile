
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY data/series.soft /app/data/series.soft
COPY data/platform_annotation.tsv /app/data/platform_annotation.tsv
COPY data/sra_runinfo.csv /app/data/sra_runinfo.csv

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 scipy==1.14.1
