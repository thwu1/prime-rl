FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip tshark && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install cryptography==44.0.0

RUN mkdir -p /app

COPY app/aes_cmac.py /app/aes_cmac.py
COPY app/config.json /app/config.json
COPY app/packet_dump.txt /app/packet_dump.txt

WORKDIR /app
