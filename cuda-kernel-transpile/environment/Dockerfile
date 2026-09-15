FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/kernels /app/data /app/output

COPY spec.json /app/spec.json
COPY fdtd_3d.cu /app/kernels/fdtd_3d.cu
COPY black_scholes.cu /app/kernels/black_scholes.cu

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 numpy==2.1.3
