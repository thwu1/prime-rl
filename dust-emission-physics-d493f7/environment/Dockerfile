FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gfortran \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY dust_physics.f90 /app/dust_physics.f90
COPY driver.f90 /app/driver.f90
COPY Makefile /app/Makefile

WORKDIR /app
