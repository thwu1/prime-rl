FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Install build dependencies for OpenSSL 3.5 and runtime tools
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    perl \
    pkg-config \
    python3-pip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Download and compile OpenSSL 3.5.0 with native ML-DSA and ML-KEM support
RUN cd /tmp && \
    wget -q https://github.com/openssl/openssl/releases/download/openssl-3.5.0/openssl-3.5.0.tar.gz && \
    tar xzf openssl-3.5.0.tar.gz && \
    cd openssl-3.5.0 && \
    ./Configure --prefix=/usr/local --openssldir=/usr/local/ssl --libdir=lib no-docs no-tests && \
    make -j$(nproc) && \
    make install_sw install_ssldirs && \
    cd / && rm -rf /tmp/openssl-3.5.0*

# Configure dynamic linker for new OpenSSL libraries
RUN printf "/usr/local/lib\n" > /etc/ld.so.conf.d/openssl-3.5.conf && ldconfig

ENV PATH="/usr/local/bin:${PATH}"
ENV LD_LIBRARY_PATH="/usr/local/lib"

RUN mkdir -p /app
WORKDIR /app

# Deploy the intentionally non-compliant PKI for audit
COPY setup_broken_pki.sh /tmp/setup_broken_pki.sh
RUN chmod +x /tmp/setup_broken_pki.sh && /tmp/setup_broken_pki.sh && rm /tmp/setup_broken_pki.sh

# Verify OpenSSL and PKI are in place
RUN openssl version && ls /app/pki/root-ca/certs/root-ca.crt /app/pki/intermediate-ca/certs/intermediate-ca.crt

