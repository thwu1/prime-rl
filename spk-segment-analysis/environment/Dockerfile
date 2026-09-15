FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    build-essential \
    wget \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

RUN wget -q https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de432s.bsp \
    -O /app/data/de432s.bsp

RUN wget -q https://naif.jpl.nasa.gov/pub/naif/generic_kernels/lsk/naif0012.tls \
    -O /app/data/naif0012.tls

WORKDIR /app
