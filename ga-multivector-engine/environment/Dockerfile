FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    rustc \
    cargo \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY libga/ /app/libga/
RUN cd /app/libga && cargo build --release

COPY ga_engine.py /app/ga_engine.py
COPY theory.md /app/theory.md

WORKDIR /app
