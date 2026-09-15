FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip g++ make && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/tqdist /app/reference

COPY tqdist/tqdist.cpp /app/tqdist/tqdist.cpp
COPY tqdist/Makefile /app/tqdist/Makefile
COPY reference/CompareQuartets.R /app/reference/CompareQuartets.R
COPY reference/Metrics.R /app/reference/Metrics.R


WORKDIR /app
