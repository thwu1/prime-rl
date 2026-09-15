FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    cargo \
    rustc \
    python3-pip \
    build-essential \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY arrow_ipc_reader/ /app/arrow_ipc_reader/

WORKDIR /app

