FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY scene.sdf /app/scene.sdf
COPY constraints.yaml /app/constraints.yaml
COPY scene_cyclic.sdf /app/scene_cyclic.sdf
COPY constraints_cyclic.yaml /app/constraints_cyclic.yaml
COPY api_spec.txt /app/api_spec.txt

WORKDIR /app
