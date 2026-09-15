FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip gfortran && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/reference
COPY config.json /app/config.json
COPY reference/pmc_constants.F90 /app/reference/pmc_constants.F90
COPY reference/aero_helpers.F90 /app/reference/aero_helpers.F90
COPY reference/coag_kernel_brown.F90 /app/reference/coag_kernel_brown.F90
COPY reference/coag_kernel_constant.F90 /app/reference/coag_kernel_constant.F90
COPY reference/coag_kernel_additive.F90 /app/reference/coag_kernel_additive.F90

