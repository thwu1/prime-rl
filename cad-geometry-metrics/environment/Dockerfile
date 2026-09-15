FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY config.json /app/config.json
COPY generate_meshes.py /tmp/generate_meshes.py
RUN python3 /tmp/generate_meshes.py && rm /tmp/generate_meshes.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 numpy==1.26.4 scipy==1.12.0 trimesh==3.23.5
