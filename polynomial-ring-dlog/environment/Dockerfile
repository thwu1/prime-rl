
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        python3 python3-pip tshark openssl xxd && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY protocol.py /app/protocol.py
COPY generate_challenge.py /tmp/generate_challenge.py

RUN pip3 install scapy==2.5.0 pycryptodome==3.21.0 -q && \
    python3 /tmp/generate_challenge.py && \
    pip3 uninstall -y scapy pycryptodome && \
    pip3 cache purge && \
    rm -f /tmp/generate_challenge.py

WORKDIR /app
