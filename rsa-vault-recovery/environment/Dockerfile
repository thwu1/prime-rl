
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y \
        python3 \
        python3-pip \
        openssl \
        tshark \
        pgpdump \
        libgmp-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/pki /app/keys /app/captures /app/pgp /app/shares

COPY vault_protocol.py /app/vault_protocol.py
COPY vault_manifest.json /app/vault_manifest.json
COPY pki/party1.pem /app/pki/party1.pem
COPY pki/party2.pem /app/pki/party2.pem
COPY pki/party3.pem /app/pki/party3.pem
COPY pgp/party6.asc /app/pgp/party6.asc
COPY shares/share1.enc /app/shares/share1.enc
COPY shares/share2.enc /app/shares/share2.enc
COPY shares/share3.enc /app/shares/share3.enc
COPY shares/share4.enc /app/shares/share4.enc
COPY shares/share6.enc /app/shares/share6.enc

COPY gen_binary_artifacts.py /tmp/gen_binary_artifacts.py
RUN python3 /tmp/gen_binary_artifacts.py && rm /tmp/gen_binary_artifacts.py

WORKDIR /app
