FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Install system packages for the task environment
RUN apt-get update && apt-get install -y \
    curl \
    jq \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install OpenBao v2.5.4
RUN ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://github.com/openbao/openbao/releases/download/v2.5.4/openbao_2.5.4_linux_${ARCH}.deb" \
    -o /tmp/openbao.deb && \
    dpkg -i /tmp/openbao.deb && \
    rm /tmp/openbao.deb

# Disable mlock for container environments
ENV BAO_DISABLE_MLOCK=true

# Create working directories
RUN mkdir -p /app/data /app/results

# Copy compliance policy and initialization script
COPY compliance_policy.txt /app/compliance_policy.txt
COPY init_state.sh /app/init_state.sh
RUN chmod +x /app/init_state.sh

# External AES-256 key for legacy import (32 bytes, hex-encoded)
COPY external_key.hex /app/external_key.hex

# Plaintext data files
COPY record1.txt /app/data/record1.txt
COPY record2.txt /app/data/record2.txt
COPY record3.txt /app/data/record3.txt
COPY sign_payload.txt /app/data/sign_payload.txt
COPY hmac_data.txt /app/data/hmac_data.txt

WORKDIR /app
