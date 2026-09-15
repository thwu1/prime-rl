
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    build-essential \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

ENV RUSTUP_HOME=/usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo
ENV PATH="/usr/local/cargo/bin:${PATH}"

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain nightly \
    && rustup component add miri \
    && cargo miri setup \
    && cargo --version \
    && cargo miri --version

ENV MIRIFLAGS="-Zmiri-tree-borrows"

WORKDIR /app
COPY Cargo.toml /app/Cargo.toml
COPY src /app/src
COPY examples /app/examples
