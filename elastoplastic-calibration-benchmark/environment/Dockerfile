FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY data/tensile_tests.json /app/data/tensile_tests.json
COPY data/bulge_test.json /app/data/bulge_test.json
COPY data/material_params.json /app/data/material_params.json
COPY data/ground_truth.json /app/data/ground_truth.json
COPY data/submissions.json /app/data/submissions.json

WORKDIR /app
