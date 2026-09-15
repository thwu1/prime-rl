FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    rustc \
    cargo \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/data
COPY Cargo.toml /app/Cargo.toml
COPY data/compression_spec.txt /app/data/compression_spec.txt
COPY data/value_semantics.txt /app/data/value_semantics.txt
COPY data/edit_distance_examples.txt /app/data/edit_distance_examples.txt

WORKDIR /app
