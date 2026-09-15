FROM openbao/openbao:latest AS bao-source
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


COPY --from=bao-source /bin/bao /usr/local/bin/bao

RUN apt-get update && apt-get install -y \
    curl jq openssl python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/keys /app/data /app/output /app/state /app/bao-data

COPY bao-config.hcl /app/bao-config.hcl
COPY records.json /app/data/records.json

RUN openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out /app/keys/rsa4096.pem 2>/dev/null && \
    openssl genpkey -algorithm ed25519 -out /app/keys/ed25519.pem 2>/dev/null

RUN chmod 600 /app/keys/*.pem

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 requests==2.32.3
