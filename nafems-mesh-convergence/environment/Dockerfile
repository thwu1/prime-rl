FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    calculix-ccx \
    gmsh \
    python3-pip \
    python3-dev \
    libglu1-mesa \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY nafems_le1_spec.json /app/nafems_le1_spec.json

WORKDIR /app
