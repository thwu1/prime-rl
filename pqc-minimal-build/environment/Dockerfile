FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    cmake \
    build-essential \
    gcc \
    g++ \
    git \
    python3-pip \
    python3-dev \
    wget \
    pkg-config \
    libssl-dev \
    ninja-build \
    binutils \
    && rm -rf /var/lib/apt/lists/*

# Download and extract liboqs 0.15.0 source
RUN mkdir -p /app/liboqs-src && \
    wget -q https://github.com/open-quantum-safe/liboqs/archive/refs/tags/0.15.0.tar.gz -O /tmp/liboqs.tar.gz && \
    tar xzf /tmp/liboqs.tar.gz -C /app/liboqs-src --strip-components=1 && \
    rm /tmp/liboqs.tar.gz

# Place the PQC migration deployment files
RUN mkdir -p /app/pqc-migration /app/output

COPY deploy.sh /app/pqc-migration/deploy.sh
COPY pqc_audit.c /app/pqc-migration/pqc_audit.c
COPY verify_migration.py /app/pqc-migration/verify_migration.py
RUN chmod +x /app/pqc-migration/deploy.sh

WORKDIR /app
