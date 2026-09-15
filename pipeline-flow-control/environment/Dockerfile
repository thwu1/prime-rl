FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Install Icarus Verilog for SystemVerilog simulation, and python3-pip
RUN apt-get update && \
    apt-get install -y iverilog python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Copy task environment files
COPY app_files/ /app/

# Make simulation script executable
RUN chmod +x /app/simulate.sh

WORKDIR /app

