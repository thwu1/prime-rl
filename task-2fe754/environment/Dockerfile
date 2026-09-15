FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libc6-dev \
    pkg-config \
    libssl-dev \
    python3-pip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Rust toolchain
ENV RUSTUP_HOME=/usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo
ENV PATH="/usr/local/cargo/bin:${PATH}"
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal

# Copy workspace source files
COPY workspace/ /app/

WORKDIR /app

# Pre-fetch dependencies to speed up agent and test execution
RUN cargo fetch
