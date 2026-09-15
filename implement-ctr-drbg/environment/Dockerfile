
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip openssl xxd && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /app/candidates /app/cavs_raw

COPY impl_A.py /app/candidates/impl_A.py
COPY impl_B.py /app/candidates/impl_B.py
COPY impl_C.py /app/candidates/impl_C.py
COPY CTR_DRBG_AES256.txt /app/cavs_raw/CTR_DRBG_AES256.txt

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 pycryptodome==3.21.0
