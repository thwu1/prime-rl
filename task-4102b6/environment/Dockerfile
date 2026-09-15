
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install scapy==2.6.1

RUN mkdir -p /app

COPY protocol_spec.txt /app/protocol_spec.txt
COPY generate_capture.py /tmp/generate_capture.py
RUN python3 /tmp/generate_capture.py && rm /tmp/generate_capture.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
