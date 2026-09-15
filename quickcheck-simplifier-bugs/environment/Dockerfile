
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Install Rust to /opt/ so it survives any /root/ volume mounts at runtime
ENV RUSTUP_HOME=/opt/rustup
ENV CARGO_HOME=/opt/cargo

RUN apt-get update && \
    apt-get install -y curl build-essential pkg-config python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable

ENV PATH="/opt/cargo/bin:${PATH}"

# Verify Rust installation
RUN cargo --version && rustc --version

COPY app/ /app/
WORKDIR /app
RUN cargo fetch
RUN cargo build
