
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip openssl libssl-dev gcc xxd && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install cryptography==44.0.0 -q

RUN mkdir -p /app/impl_alpha /app/impl_beta /app/vectors

COPY impl_alpha/ctr_drbg.py /app/impl_alpha/ctr_drbg.py
COPY impl_beta/ctrdrbg.h /app/impl_beta/ctrdrbg.h
COPY impl_beta/ctrdrbg.c /app/impl_beta/ctrdrbg.c
COPY vectors/CTR_DRBG_AES256.rsp /app/vectors/CTR_DRBG_AES256.rsp
COPY vectors/CTR_DRBG_AES256_intermediate.txt /app/vectors/CTR_DRBG_AES256_intermediate.txt
COPY run_validation.py /app/run_validation.py

RUN gcc -shared -fPIC -O2 -o /app/impl_beta/libctrdrbg.so /app/impl_beta/ctrdrbg.c -lcrypto

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
