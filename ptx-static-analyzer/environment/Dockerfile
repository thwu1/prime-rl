
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    llvm-18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN mkdir -p /app/kernels

COPY kernels/vecadd.ptx /app/kernels/vecadd.ptx
COPY kernels/reduce.ptx /app/kernels/reduce.ptx
COPY kernels/matmul.ll /app/kernels/matmul.ll
