FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip gcc make sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

WORKDIR /app

COPY gmpb_native/ /app/gmpb_native/
COPY gmpb_bridge_stub.py /app/gmpb_bridge_stub.py
