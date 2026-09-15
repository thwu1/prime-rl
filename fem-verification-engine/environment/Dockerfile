FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/benchmarks

COPY benchmarks/thick_cylinder.json /app/benchmarks/thick_cylinder.json
COPY benchmarks/piston_fluid.json /app/benchmarks/piston_fluid.json
COPY benchmarks/foundation_buckling.json /app/benchmarks/foundation_buckling.json
COPY benchmarks/plasticity_cycle.json /app/benchmarks/plasticity_cycle.json
COPY benchmarks/composite_laminate.json /app/benchmarks/composite_laminate.json

WORKDIR /app
