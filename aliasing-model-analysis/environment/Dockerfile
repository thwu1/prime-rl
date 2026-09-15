FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    cargo \
    rustc \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY Cargo.toml /app/Cargo.toml
COPY src/ /app/src/
COPY diagnostics/ /app/diagnostics/
COPY NOTES.md /app/NOTES.md

RUN cargo build 2>&1
