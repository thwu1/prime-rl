
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    pkg-config \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install Rust toolchain
ENV RUSTUP_HOME=/usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
ENV PATH="/usr/local/cargo/bin:${PATH}"

# Set up project structure
COPY Cargo.toml /app/Cargo.toml
COPY src/ /app/src/

# Generate deterministic test data
COPY gen_data.py /tmp/gen_data.py
RUN python3 /tmp/gen_data.py && rm /tmp/gen_data.py

WORKDIR /app

# Pre-build the project and run programs to populate output with initial results
RUN cargo build --release
RUN ./target/release/transitive_closure && \
    ./target/release/triangles && \
    ./target/release/reaching_defs && \
    ./target/release/scc
