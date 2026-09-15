FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    openssl \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install cryptography==42.0.5

COPY generate_broken_pki.py /tmp/generate_broken_pki.py
RUN python3 /tmp/generate_broken_pki.py && rm /tmp/generate_broken_pki.py

WORKDIR /app
