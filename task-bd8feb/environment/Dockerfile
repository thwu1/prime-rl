FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential \
    python3-pip \
    cargo \
    rustc \
    && rm -rf /var/lib/apt/lists/*

COPY app/ /app/

WORKDIR /app
RUN cargo build --release
