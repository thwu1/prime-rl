FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    yosys \
    iverilog \
    && rm -rf /var/lib/apt/lists/*

COPY cells.lib /app/cells.lib
COPY netlist.v /app/netlist.v
COPY design.v /app/design.v
COPY cells_sim.v /app/cells_sim.v
COPY constraints.sdc /app/constraints.sdc

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
