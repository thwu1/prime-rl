
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip curl build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"

RUN mkdir -p /app/reference /app/k256-harness/src

COPY secp256k1.py /app/secp256k1.py
COPY bip340.py /app/bip340.py
COPY test_vectors.json /app/test_vectors.json
COPY k256_projective.rs /app/reference/k256_projective.rs
COPY Cargo.toml /app/k256-harness/Cargo.toml
COPY harness_main.rs /app/k256-harness/src/main.rs

WORKDIR /app
