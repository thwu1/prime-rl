
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    bc \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY setup_app.py /tmp/setup_app.py
RUN python3 /tmp/setup_app.py && rm /tmp/setup_app.py

WORKDIR /app
