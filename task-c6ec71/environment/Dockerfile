FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    gcc \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY bezier.py /app/bezier.py
COPY coefficients.py /app/coefficients.py
COPY quadrature.h /app/quadrature.h
COPY Makefile /app/Makefile
COPY arclength_stub.py /app/arclength_stub.py
COPY reference_curves.json /app/reference_curves.json
COPY evaluate.py /app/evaluate.py
COPY SPEC.md /app/SPEC.md

WORKDIR /app
