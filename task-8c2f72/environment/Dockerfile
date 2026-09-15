FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV OMPI_MCA_osc=pt2pt
ENV OMPI_ALLOW_RUN_AS_ROOT=1
ENV OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1

RUN apt-get update && apt-get install -y \
    build-essential \
    libopenmpi-dev \
    openmpi-bin \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
COPY solver_parallel.c /app/solver_parallel.c
COPY solver_serial.c /app/solver_serial.c
COPY Makefile /app/Makefile
WORKDIR /app
