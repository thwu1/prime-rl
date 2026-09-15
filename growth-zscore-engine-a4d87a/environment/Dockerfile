FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    r-base \
    r-cran-jsonlite \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Canary

WORKDIR /app

COPY data/ /app/data/
COPY growth_engine.R /app/growth_engine.R
