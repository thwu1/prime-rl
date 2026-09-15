FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Install build tools, Rust toolchain, and python3-pip
RUN apt-get update && apt-get install -y \
    build-essential \
    cargo \
    rustc \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Copy project skeleton
COPY app/ /app/

# Pre-build to cache dependencies (stubs compile but panic at runtime)
WORKDIR /app
RUN cargo build --release

