
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    clang \
    llvm \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Ensure unversioned opt/clang symlinks exist
RUN if ! command -v opt > /dev/null 2>&1; then \
        for v in 18 17 16; do \
            if command -v opt-$v > /dev/null 2>&1; then \
                ln -s $(command -v opt-$v) /usr/local/bin/opt; \
                break; \
            fi; \
        done; \
    fi && \
    if ! command -v clang > /dev/null 2>&1; then \
        for v in 18 17 16; do \
            if command -v clang-$v > /dev/null 2>&1; then \
                ln -s $(command -v clang-$v) /usr/local/bin/clang; \
                break; \
            fi; \
        done; \
    fi

COPY app/benchmarks/ /app/benchmarks/
COPY app/src/ /app/src/
COPY app/run.py /app/run.py

# Compile C benchmark sources to LLVM IR (unoptimized, without optnone)
RUN cd /app/benchmarks && \
    for f in *.c; do \
        clang -S -emit-llvm -O0 -Xclang -disable-O0-optnone \
            "$f" -o "${f%.c}.ll"; \
    done

WORKDIR /app
