FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install scapy==2.6.1 cryptography==44.0.0

COPY generate_challenge.py /tmp/generate_challenge.py
RUN python3 /tmp/generate_challenge.py && \
    rm -f /tmp/generate_challenge.py && \
    rm -rf /root/.cache/pip /tmp/__pycache__

WORKDIR /app
