FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV JAX_PLATFORMS=cpu


RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install bloqade-tsim quantum circuit simulator (task environment tool)
RUN pip3 install bloqade-tsim==0.1.4

RUN mkdir -p /app
WORKDIR /app
