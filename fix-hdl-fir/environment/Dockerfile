FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3-pip \
    verilator \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/sim

COPY Makefile /app/Makefile
COPY src/fir_pkg.sv /app/src/fir_pkg.sv
COPY src/fir_engine.sv /app/src/fir_engine.sv
COPY src/fir_top.sv /app/src/fir_top.sv
COPY src/fir_core.sv /app/src/fir_core.sv
COPY src/coeff_rom.sv /app/src/coeff_rom.sv
COPY sim/sim_main.cpp /app/sim/sim_main.cpp

WORKDIR /app
