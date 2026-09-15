FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc-riscv64-linux-gnu \
    binutils-riscv64-linux-gnu \
    libc6-dev-riscv64-cross \
    qemu-user \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/kernels /app/optimized /app/build

COPY kernels/ /app/kernels/

WORKDIR /app
