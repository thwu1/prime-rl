FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Use /opt paths so the toolchain survives runtime volume mounts on /root
ENV RUSTUP_HOME=/opt/rustup
ENV CARGO_HOME=/opt/cargo
ENV HOME=/root

RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    build-essential \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install rustup with the exact Rust toolchain that Verus 0.2026.05.31 requires
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --default-toolchain 1.95.0-x86_64-unknown-linux-gnu

ENV PATH="/opt/cargo/bin:/opt/verus:${PATH}"

# Verify rustup and the toolchain are working
RUN rustup --version && rustc --version && rustup show

# Download and install Verus binary release (stable weekly)
RUN curl -fL -o /tmp/verus.zip \
    https://github.com/verus-lang/verus/releases/download/release/0.2026.05.31.5dd6d83/verus-0.2026.05.31.5dd6d83-x86-linux.zip && \
    cd /opt && \
    unzip /tmp/verus.zip && \
    mv verus-x86-linux verus && \
    chmod +x /opt/verus/verus && \
    rm /tmp/verus.zip

# Smoke-test: verus should find rustup and the toolchain now
RUN verus --help 2>&1 | head -5 || true
RUN which rustup && which rustc

# Set up task workspace with the incomplete source file
RUN mkdir -p /app
COPY verified_algorithms.rs /app/verified_algorithms.rs

WORKDIR /app
