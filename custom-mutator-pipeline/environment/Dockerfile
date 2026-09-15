FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential gcc g++ \
    clang llvm llvm-dev lld \
    python3 python3-dev python3-pip \
    zlib1g-dev \
    git curl \
    && rm -rf /var/lib/apt/lists/*

# Build AFL++ from source with Python custom mutator support
RUN git clone --depth=1 https://github.com/AFLplusplus/AFLplusplus /tmp/aflpp && \
    cd /tmp/aflpp && \
    export NO_NYX=1 && \
    export NO_CORESIGHT=1 && \
    make -j$(nproc) source-only && \
    make install && \
    cd / && rm -rf /tmp/aflpp

COPY protocol_spec.md /app/docs/protocol_spec.md
COPY validate.py /app/validator/validate.py
COPY target.c /app/target/target.c

WORKDIR /app
