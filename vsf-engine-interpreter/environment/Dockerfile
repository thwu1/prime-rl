FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip openssl curl jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/pki

COPY vsf_config /app/vsf_config
COPY spec.md /app/spec.md
COPY totp_seed.txt /app/totp_seed.txt
COPY jwt_secret.txt /app/jwt_secret.txt

WORKDIR /app
