FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    clang \
    llvm \
    python3-pip \
    python3 \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

# Verify toolchain is available and functional
RUN which clang && which opt
RUN echo "int f(int x){return x+1;}" > /tmp/_v.c && \
    clang -O0 -Xclang -disable-O0-optnone -emit-llvm -S /tmp/_v.c -o /tmp/_v.ll && \
    opt -Oz -S /tmp/_v.ll > /dev/null && \
    opt --passes=instcombine -S /tmp/_v.ll > /dev/null && \
    rm /tmp/_v.c /tmp/_v.ll

RUN mkdir -p /app/benchmarks

COPY benchmarks/redundant_compute.c /tmp/benchmarks/redundant_compute.c
COPY benchmarks/control_flow.c /tmp/benchmarks/control_flow.c
COPY benchmarks/loop_heavy.c /tmp/benchmarks/loop_heavy.c
COPY benchmarks/memory_access.c /tmp/benchmarks/memory_access.c
COPY benchmarks/mixed_ops.c /tmp/benchmarks/mixed_ops.c

RUN clang -O0 -Xclang -disable-O0-optnone -emit-llvm -S /tmp/benchmarks/redundant_compute.c -o /app/benchmarks/redundant_compute.ll && \
    clang -O0 -Xclang -disable-O0-optnone -emit-llvm -S /tmp/benchmarks/control_flow.c -o /app/benchmarks/control_flow.ll && \
    clang -O0 -Xclang -disable-O0-optnone -emit-llvm -S /tmp/benchmarks/loop_heavy.c -o /app/benchmarks/loop_heavy.ll && \
    clang -O0 -Xclang -disable-O0-optnone -emit-llvm -S /tmp/benchmarks/memory_access.c -o /app/benchmarks/memory_access.ll && \
    clang -O0 -Xclang -disable-O0-optnone -emit-llvm -S /tmp/benchmarks/mixed_ops.c -o /app/benchmarks/mixed_ops.ll && \
    rm -rf /tmp/benchmarks

COPY synergy_pairs.json /app/synergy_pairs.json
COPY instcount.py /app/instcount.py

WORKDIR /app
