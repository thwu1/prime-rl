FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    openssl \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY legacy_openssl.cnf /tmp/legacy_openssl.cnf
COPY setup_broken_pki.sh /tmp/setup_broken_pki.sh
RUN chmod +x /tmp/setup_broken_pki.sh && /tmp/setup_broken_pki.sh && rm /tmp/setup_broken_pki.sh /tmp/legacy_openssl.cnf

WORKDIR /app
