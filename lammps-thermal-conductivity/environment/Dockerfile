FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y software-properties-common && \
    add-apt-repository -y universe && \
    apt-get update && \
    apt-get install -y lammps python3-pip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY in.heat /app/in.heat
COPY in.mp /app/in.mp
