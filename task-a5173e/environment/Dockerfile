FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    iverilog \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
COPY app/aes128_encrypt.v /app/aes128_encrypt.v
COPY app/aes128_decrypt.v /app/aes128_decrypt.v
COPY app/tb_aes128_decrypt.v /app/tb_aes128_decrypt.v
COPY app/Makefile /app/Makefile
WORKDIR /app
