FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    r-base \
    r-cran-jsonlite \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY brdf_pipeline.R /app/brdf_pipeline.R
COPY kernels.R /app/kernels.R
COPY config.json /app/config.json
COPY data /app/data

WORKDIR /app

