FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    build-essential \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY gen_instances.py /tmp/gen_instances.py
RUN python3 /tmp/gen_instances.py && rm /tmp/gen_instances.py

WORKDIR /app
