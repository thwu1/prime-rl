FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libopenblas-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY app/ /app/

# Save pristine copies of harness files for integrity verification
RUN mkdir -p /app/originals && \
    cp /app/dgemm-naive.c /app/originals/dgemm-naive.c && \
    cp /app/dgemm-blas.c /app/originals/dgemm-blas.c && \
    cp /app/benchmark.cpp /app/originals/benchmark.cpp && \
    cp /app/CMakeLists.txt /app/originals/CMakeLists.txt

WORKDIR /app
