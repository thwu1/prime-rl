FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY generate_capture.py /tmp/generate_capture.py
RUN pip3 install cryptography==42.0.5 -q && \
    python3 /tmp/generate_capture.py && \
    pip3 uninstall -y cryptography -q && \
    rm /tmp/generate_capture.py

WORKDIR /app
