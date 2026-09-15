FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install cryptography==43.0.3

RUN mkdir -p /app/vectors

RUN curl -fsSL -o /app/vectors/aes_gcm_test.json \
    "https://raw.githubusercontent.com/C2SP/wycheproof/main/testvectors_v1/aes_gcm_test.json"

RUN curl -fsSL -o /app/vectors/ecdsa_secp256r1_sha256_test.json \
    "https://raw.githubusercontent.com/C2SP/wycheproof/main/testvectors_v1/ecdsa_secp256r1_sha256_test.json"

RUN curl -fsSL -o /app/vectors/hmac_sha256_test.json \
    "https://raw.githubusercontent.com/C2SP/wycheproof/main/testvectors_v1/hmac_sha256_test.json"

RUN curl -fsSL -o /app/vectors/hkdf_sha256_test.json \
    "https://raw.githubusercontent.com/C2SP/wycheproof/main/testvectors_v1/hkdf_sha256_test.json"

COPY crypto_ops.py /app/crypto_ops.py

WORKDIR /app
