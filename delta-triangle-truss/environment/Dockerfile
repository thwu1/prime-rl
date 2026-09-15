FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip curl build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Rust toolchain (needed to build and modify the graph engine)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

RUN mkdir -p /data /app/output /app/scripts /app/graph-engine/src

COPY app/graph-engine/Cargo.toml /app/graph-engine/Cargo.toml
COPY app/graph-engine/src/lib.rs /app/graph-engine/src/lib.rs
COPY app/graph-engine/src/main.rs /app/graph-engine/src/main.rs

COPY app/scripts/truss.py /app/scripts/truss.py
COPY app/Makefile /app/Makefile
COPY app/SPEC.md /app/SPEC.md

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app
