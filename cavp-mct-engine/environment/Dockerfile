
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-dev libssl-dev && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/vectors /app/audit

COPY vectors/CBCMCT128.rsp /app/vectors/CBCMCT128.rsp
COPY vectors/CBCMCT192.rsp /app/vectors/CBCMCT192.rsp
COPY vectors/CBCMCT256.rsp /app/vectors/CBCMCT256.rsp
COPY audit/CBCMCT128_suspect.rsp /app/audit/CBCMCT128_suspect.rsp
COPY challenge.json /app/challenge.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 pycryptodome==3.21.0
