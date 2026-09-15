FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY data/action_table.tsv /app/data/action_table.tsv
COPY data/spec_normative.txt /app/data/spec_normative.txt


WORKDIR /app
