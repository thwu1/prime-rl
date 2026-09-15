
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    build-essential \
    ca-certificates \
    cargo \
    curl \
    libssl-dev \
    pkg-config \
    python3-pip \
    rustc \
    && rm -rf /var/lib/apt/lists/*

# Verify Rust toolchain is in standard PATH
RUN rustc --version && cargo --version

# Copy skeleton project
COPY app/ /app/

WORKDIR /app

# Pre-download and compile dependencies (library build may fail with todo!() stubs, that's ok)
RUN cargo fetch && cargo build 2>/dev/null || true
