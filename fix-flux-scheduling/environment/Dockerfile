FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3 \
    wget \
    bzip2 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Miniforge (provides conda/mamba for Flux installation)
RUN wget -q https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O /tmp/miniforge.sh && \
    bash /tmp/miniforge.sh -b -p /opt/conda && \
    rm /tmp/miniforge.sh

ENV PATH="/opt/conda/bin:$PATH"

# Install Flux Framework core (includes broker, sched-simple, CLI tools)
RUN mamba install -y -c conda-forge flux-core && \
    mamba clean -afy

# Create non-root user for running Flux instances
RUN useradd -m -s /bin/bash fluxuser

# Set up working directories
RUN mkdir -p /app/broken-config /app/fixed-config && \
    chmod -R 777 /app

COPY broken-config/ /app/broken-config/

WORKDIR /app
