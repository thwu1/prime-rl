FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc-riscv64-linux-gnu \
    g++-riscv64-linux-gnu \
    binutils-riscv64-linux-gnu \
    clang \
    llvm \
    lld \
    qemu-user-static \
    python3-pip \
    build-essential \
    file \
    && rm -rf /var/lib/apt/lists/*

COPY src/ /app/src/

RUN mkdir -p /app/baseline /app/optimized /app/results

RUN cp /app/src/math_utils.c /app/baseline/original_math_utils.c

RUN cd /app/src && \
    riscv64-linux-gnu-gcc -O3 -march=rv64imafd -mabi=lp64d -c main.c -o /app/baseline/main.o && \
    riscv64-linux-gnu-gcc -O3 -march=rv64imafd -mabi=lp64d -c crypto.c -o /app/baseline/crypto.o && \
    riscv64-linux-gnu-gcc -O3 -march=rv64imafd -mabi=lp64d -c math_utils.c -o /app/baseline/math_utils.o && \
    riscv64-linux-gnu-gcc -O3 -march=rv64imafd -mabi=lp64d -c compress.c -o /app/baseline/compress.o && \
    riscv64-linux-gnu-gcc -O3 -march=rv64imafd -mabi=lp64d -static \
        /app/baseline/main.o /app/baseline/crypto.o \
        /app/baseline/math_utils.o /app/baseline/compress.o \
        -o /app/baseline/firmware.elf -lm && \
    riscv64-linux-gnu-size /app/baseline/*.o > /app/baseline/sizes.txt && \
    riscv64-linux-gnu-size /app/baseline/firmware.elf >> /app/baseline/sizes.txt

WORKDIR /app
