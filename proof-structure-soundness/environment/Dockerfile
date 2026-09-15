FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    tcl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/constraints

COPY proof_plan.tcl /app/proof_plan.tcl
COPY design_spec.json /app/design_spec.json
COPY constraints/access_type.smt2 /app/constraints/access_type.smt2
COPY constraints/dma_mode.smt2 /app/constraints/dma_mode.smt2
COPY constraints/power_state.smt2 /app/constraints/power_state.smt2
COPY constraints/error_class.smt2 /app/constraints/error_class.smt2

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
