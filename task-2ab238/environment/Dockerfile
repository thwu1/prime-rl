FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y openssl python3-pip nginx && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/pki

COPY dhparams.pem /app/pki/dhparams.pem
COPY setup_broken_pki.sh /tmp/setup_broken_pki.sh
RUN chmod +x /tmp/setup_broken_pki.sh && \
    bash /tmp/setup_broken_pki.sh && \
    rm /tmp/setup_broken_pki.sh

WORKDIR /app
