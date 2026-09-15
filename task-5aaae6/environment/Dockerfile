FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    cargo \
    rustc \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY app/ /app/

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 maturin==1.7.8
