FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY c_src/ /app/c_src/
COPY rust_src/ /app/rust_src/

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
