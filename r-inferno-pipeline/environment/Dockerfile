FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    r-base \
    r-cran-jsonlite \
    python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/lib /app/output

COPY measurements.csv /app/data/measurements.csv
COPY pipeline.R /app/pipeline.R
COPY lib/transforms.R /app/lib/transforms.R
COPY lib/statistics.R /app/lib/statistics.R

WORKDIR /app
