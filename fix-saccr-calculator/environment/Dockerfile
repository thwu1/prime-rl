FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    r-base \
    r-cran-jsonlite \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY core.R /app/core.R
COPY addons.R /app/addons.R
COPY saccr.R /app/saccr.R
COPY data/ /app/data/

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
