FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/vault/data /app/vault/patches

COPY crypto_utils.py /app/vault/crypto_utils.py
COPY vault_readme.txt /app/vault/README.txt
COPY data/pubkey.json /app/vault/data/pubkey.json
COPY data/debug_log.txt /app/vault/data/debug_log.txt
COPY data/encrypted_flag.hex /app/vault/data/encrypted_flag.hex
COPY data/encrypted_aes_key.hex /app/vault/data/encrypted_aes_key.hex
COPY data/aes_nonce.hex /app/vault/data/aes_nonce.hex
COPY patches/patch_a.py /app/vault/patches/patch_a.py
COPY patches/patch_b.py /app/vault/patches/patch_b.py
COPY patches/patch_c.py /app/vault/patches/patch_c.py

WORKDIR /app
