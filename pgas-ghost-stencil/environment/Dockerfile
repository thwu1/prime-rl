FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


ENV OMPI_ALLOW_RUN_AS_ROOT=1
ENV OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1
ENV OMPI_MCA_osc=pt2pt

RUN apt-get update && apt-get install -y \
    build-essential \
    openmpi-bin \
    libopenmpi-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY app/ /app/

WORKDIR /app
