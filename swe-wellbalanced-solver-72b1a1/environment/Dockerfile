FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/params /app/src /app/lib /app/output

COPY app/swe1d.py /app/swe1d.py
COPY app/Makefile /app/Makefile
COPY app/src/flux_kernels.c /app/src/flux_kernels.c
COPY app/src/flux_kernels.h /app/src/flux_kernels.h
COPY app/params/lake_at_rest.dat /app/params/lake_at_rest.dat
COPY app/params/dam_break_dry.dat /app/params/dam_break_dry.dat
COPY app/params/dam_break_wet.dat /app/params/dam_break_wet.dat
COPY app/params/subcritical_bump.dat /app/params/subcritical_bump.dat
COPY app/params/transcritical_shock.dat /app/params/transcritical_shock.dat

