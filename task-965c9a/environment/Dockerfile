FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y \
        python3 \
        python3-pip \
        libssl-dev \
        openssl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/vectors /app/responses

COPY vectors/sha2_256_prompt.json /app/vectors/sha2_256_prompt.json
COPY vectors/ctrdrbg_prompt.json /app/vectors/ctrdrbg_prompt.json
COPY vectors/aes_gcm_prompt.json /app/vectors/aes_gcm_prompt.json

WORKDIR /app
