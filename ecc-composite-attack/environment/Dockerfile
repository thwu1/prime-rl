
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-pip \
        python3-dev \
        build-essential \
        libgmp-dev \
        libmpfr-dev \
        libmpc-dev \
        gmp-ecm \
        pari-gp \
        openssl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/challenge

COPY encrypt.py /app/challenge/encrypt.py
COPY public_params.json /app/challenge/public_params.json
COPY encrypted_payload.b64 /app/challenge/encrypted_payload.b64
COPY key_derivation.json /app/challenge/key_derivation.json
COPY proposed_remediations.json /app/challenge/proposed_remediations.json
COPY security_requirements.txt /app/challenge/security_requirements.txt

WORKDIR /app
