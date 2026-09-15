FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    iverilog \
    make \
    && rm -rf /var/lib/apt/lists/*

COPY rvfi_validator/ /app/rvfi_validator/
COPY reference_models/ /app/reference_models/
COPY rvfi_reference.md /app/rvfi_reference.md
COPY riscv_m_extension.md /app/riscv_m_extension.md

WORKDIR /app
