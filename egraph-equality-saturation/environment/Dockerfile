
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV CARGO_HOME="/usr/local/cargo"
ENV RUSTUP_HOME="/usr/local/rustup"
ENV PATH="/usr/local/cargo/bin:${PATH}"

RUN apt-get update && apt-get install -y \
    python3-pip \
    build-essential \
    curl \
    pkg-config \
    libssl-dev \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable

COPY Cargo.toml /app/Cargo.toml
RUN mkdir -p /app/src && \
    echo 'fn main() {}' > /app/src/main.rs && \
    cd /app && cargo build --release

COPY stub_main.rs /app/src/main.rs
RUN cd /app && cargo build --release

COPY inputs.json /app/inputs.json

WORKDIR /app
