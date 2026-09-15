
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip xxd binutils jq && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY generate_dumps.py /tmp/generate_dumps.py
RUN python3 /tmp/generate_dumps.py && rm /tmp/generate_dumps.py

COPY format_reference.txt /app/dumps/FORMAT.txt
