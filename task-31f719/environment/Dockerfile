FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip curl build-essential pkg-config && rm -rf /var/lib/apt/lists/*

# Install Rust toolchain
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"

# Make cargo/rustc accessible even if PATH is reset at runtime
RUN ln -sf /root/.cargo/bin/cargo /usr/local/bin/cargo && \
    ln -sf /root/.cargo/bin/rustc /usr/local/bin/rustc && \
    ln -sf /root/.cargo/bin/rustup /usr/local/bin/rustup

# Set up workspace
COPY workspace/ /app/workspace/
COPY queries.json /app/queries.json

# Generate lockfile so cargo commands work immediately
WORKDIR /app/workspace
RUN cargo generate-lockfile

WORKDIR /app
