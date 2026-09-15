FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    gcc make pkg-config \
    libgsl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src

COPY quadrature.py /app/quadrature.py
COPY gsl_bridge.py /app/gsl_bridge.py
COPY run_benchmarks.py /app/run_benchmarks.py
COPY integrands.py /app/integrands.py
COPY evaluate.py /app/evaluate.py
COPY Makefile /app/Makefile
COPY src/quad_wrapper.c /app/src/quad_wrapper.c
COPY src/quad_wrapper.h /app/src/quad_wrapper.h

WORKDIR /app
