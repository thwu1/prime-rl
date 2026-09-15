FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    iverilog \
    yosys \
    python3-pip \
    make \
    && rm -rf /var/lib/apt/lists/*

COPY src/ /app/

RUN mkdir -p /app/results

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
