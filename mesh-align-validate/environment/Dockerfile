
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    libgl1 \
    libx11-6 \
    libgomp1 \
    libglu1-mesa \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install open3d==0.19.0 trimesh==4.5.3 numpy==2.1.3 scipy==1.14.1 pyyaml==6.0.2 -q

RUN mkdir -p /app/meshes

COPY config.yaml /app/config.yaml
COPY mesh_validator.py /app/mesh_validator.py
COPY setup_meshes.py /tmp/setup_meshes.py

RUN python3 /tmp/setup_meshes.py && rm /tmp/setup_meshes.py

WORKDIR /app
