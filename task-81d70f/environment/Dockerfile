FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    llvm-18 clang-18 python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/opt-18 /usr/bin/opt \
    && ln -s /usr/bin/clang-18 /usr/bin/clang \
    && ln -s /usr/bin/llvm-as-18 /usr/bin/llvm-as \
    && ln -s /usr/bin/llc-18 /usr/bin/llc

COPY benchmarks/ /tmp/benchmarks/
RUN mkdir -p /app/benchmarks && \
    for f in /tmp/benchmarks/*.c; do \
        name=$(basename "$f" .c); \
        clang-18 -S -emit-llvm -O0 -Xclang -disable-O0-optnone \
            "$f" -o "/app/benchmarks/${name}.ll" || exit 1; \
    done && \
    test -f /app/benchmarks/bitmanip.ll && \
    test -f /app/benchmarks/crypto_hash.ll && \
    test -f /app/benchmarks/dsp_filter.ll && \
    test -f /app/benchmarks/graph_ops.ll && \
    test -f /app/benchmarks/matrix_ops.ll && \
    test -f /app/benchmarks/poly_eval.ll && \
    test -f /app/benchmarks/sort_search.ll && \
    rm -rf /tmp/benchmarks

COPY count_ir.py /app/count_ir.py
RUN chmod +x /app/count_ir.py

WORKDIR /app
