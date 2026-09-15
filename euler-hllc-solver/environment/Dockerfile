FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/config /app/results

COPY create_config.py /tmp/create_config.py
RUN python3 /tmp/create_config.py && rm /tmp/create_config.py

WORKDIR /app
