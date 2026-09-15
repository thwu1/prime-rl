FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    libglu1-mesa \
    libgl1 \
    libgomp1 \
    libxcursor1 \
    libxft2 \
    libxinerama1 \
    libfontconfig1 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
WORKDIR /app

COPY rve_config.json /app/rve_config.json
COPY mesher.py /app/mesher.py

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q gmsh==4.12.2 numpy==2.1.3 pytest==8.3.4
