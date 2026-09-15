FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    r-base \
    r-cran-jsonlite \
    python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY patients.csv /app/patients.csv
COPY fetal_biometry.R /app/fetal_biometry.R
COPY doppler_surveillance.R /app/doppler_surveillance.R
COPY run_pipeline.R /app/run_pipeline.R

