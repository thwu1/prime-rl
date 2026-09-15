FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y python3 python3-pip tshark && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY generate_traffic.py /tmp/generate_traffic.py
COPY scenario.txt /app/scenario.txt

RUN python3 /tmp/generate_traffic.py && rm /tmp/generate_traffic.py

WORKDIR /app
