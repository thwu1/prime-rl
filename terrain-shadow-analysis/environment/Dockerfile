FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-numpy \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY generate_data.py /tmp/generate_data.py
COPY config.json /app/data/config.json
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app
