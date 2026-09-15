FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Install ngspice circuit simulator and python3-pip
RUN apt-get update && \
    apt-get install -y ngspice python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Create working directories
RUN mkdir -p /app/results

# Copy broken PSPICE-format netlists for both topologies
COPY files/async_boost.cir /app/async_boost.cir
COPY files/sync_boost.cir /app/sync_boost.cir

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
