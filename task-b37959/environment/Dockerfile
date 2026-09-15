
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/problem

COPY chains.json /app/problem/chains.json
COPY blas_reference.txt /app/problem/blas_reference.txt
COPY blas_test_spec.json /app/problem/blas_test_spec.json

WORKDIR /app
