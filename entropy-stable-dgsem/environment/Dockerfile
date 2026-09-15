FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-numpy \
    make \
    jq \
    gawk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY core.py /app/core.py
COPY fluxes.py /app/fluxes.py
COPY run_study.py /app/run_study.py
COPY Makefile /app/Makefile

RUN mkdir -p /app/results
