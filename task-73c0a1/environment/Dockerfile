FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip sigrok-cli \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY generate_capture.py /tmp/generate_capture.py
COPY expected_schema.json /app/expected_schema.json

RUN python3 /tmp/generate_capture.py && rm /tmp/generate_capture.py

WORKDIR /app
