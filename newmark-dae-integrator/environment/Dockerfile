FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

RUN mkdir -p /app/simulation /app/results /app/native

COPY simulation_config.py /app/simulation/config.py
COPY simulation_bodies.py /app/simulation/bodies.py
COPY simulation_constraints.py /app/simulation/constraints.py
COPY simulation_integrator.py /app/simulation/integrator.py
COPY simulation_run_simulation.py /app/run_simulation.py
COPY simulation_verify.py /app/verify.py

COPY native_constraints.c /app/native/constraints_native.c
COPY native_makefile /app/native/Makefile

WORKDIR /app
