
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install cryptography==44.0.0

RUN mkdir -p /app/vectors

RUN wget -q -O /app/vectors/aes_gcm_test.json \
    "https://raw.githubusercontent.com/C2SP/wycheproof/master/testvectors_v1/aes_gcm_test.json" && \
    wget -q -O /app/vectors/ecdsa_secp256r1_sha256_test.json \
    "https://raw.githubusercontent.com/C2SP/wycheproof/master/testvectors_v1/ecdsa_secp256r1_sha256_test.json" && \
    wget -q -O /app/vectors/hmac_sha256_test.json \
    "https://raw.githubusercontent.com/C2SP/wycheproof/master/testvectors_v1/hmac_sha256_test.json" && \
    wget -q -O /app/vectors/x25519_test.json \
    "https://raw.githubusercontent.com/C2SP/wycheproof/master/testvectors_v1/x25519_test.json" && \
    wget -q -O /app/vectors/hkdf_sha256_test.json \
    "https://raw.githubusercontent.com/C2SP/wycheproof/master/testvectors_v1/hkdf_sha256_test.json"

COPY app/crypto_service.py /app/crypto_service.py

WORKDIR /app
