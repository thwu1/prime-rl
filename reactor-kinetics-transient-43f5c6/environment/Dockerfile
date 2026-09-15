FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gfortran \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/results

COPY data/reactor.inp /app/data/reactor.inp
COPY data/scenarios.json /app/data/scenarios.json
COPY data/spectral_feedback.f90 /app/data/spectral_feedback.f90

WORKDIR /app
