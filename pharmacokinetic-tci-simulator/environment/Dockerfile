FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    r-base \
    r-cran-jsonlite \
    python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY pk_simulator.R /app/pk_simulator.R
COPY run_simulation.R /app/run_simulation.R
COPY scenarios.json /app/scenarios.json

WORKDIR /app
