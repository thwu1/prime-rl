FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    gcc \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/candidates /app/patched

COPY keccak.c /app/keccak.c
COPY keccak.h /app/keccak.h
COPY Makefile /app/Makefile

RUN cd /app && make

COPY keccak_ffi.py /app/keccak_ffi.py
COPY test_vectors.json /app/test_vectors.json

COPY vendor_alpha.py /app/candidates/vendor_alpha.py
COPY vendor_beta.py /app/candidates/vendor_beta.py
COPY vendor_gamma.py /app/candidates/vendor_gamma.py
COPY vendor_delta.py /app/candidates/vendor_delta.py

WORKDIR /app
