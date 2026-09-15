
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

COPY model/ /app/model/
COPY gen_rch.py /tmp/gen_rch.py
RUN python3 /tmp/gen_rch.py && rm /tmp/gen_rch.py

RUN mkdir -p /app/results

WORKDIR /app
