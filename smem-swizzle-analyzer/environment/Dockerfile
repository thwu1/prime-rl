
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip python3-yaml build-essential cmake && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/smem_optimizer

COPY CMakeLists.txt /app/CMakeLists.txt
COPY Makefile /app/Makefile
COPY kernel_configs.yaml /app/kernel_configs.yaml
COPY run_optimizer.py /app/run_optimizer.py
COPY src/smem_bank.h /app/src/smem_bank.h
COPY src/smem_bank.c /app/src/smem_bank.c
COPY smem_optimizer/__init__.py /app/smem_optimizer/__init__.py
COPY smem_optimizer/banking.py /app/smem_optimizer/banking.py
COPY smem_optimizer/swizzle.py /app/smem_optimizer/swizzle.py
COPY smem_optimizer/padding.py /app/smem_optimizer/padding.py
COPY smem_optimizer/evaluator.py /app/smem_optimizer/evaluator.py

WORKDIR /app
