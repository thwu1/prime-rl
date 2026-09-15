FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-pip \
        calculix-ccx \
        gmsh \
    && rm -rf /var/lib/apt/lists/*

COPY project /app/project

WORKDIR /app
