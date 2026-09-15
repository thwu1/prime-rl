
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        xxd \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.0.2 tifffile==2024.8.30

COPY generate_corrupted.py /tmp/generate_corrupted.py
RUN python3 /tmp/generate_corrupted.py && rm /tmp/generate_corrupted.py

RUN mkdir -p /app
WORKDIR /app
