
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    tshark \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install scapy==2.6.1

COPY app/ /data/

RUN python3 /data/generate_pcaps.py && rm /data/generate_pcaps.py

RUN mkdir -p /app

WORKDIR /app
