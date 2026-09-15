FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    llvm-18 \
    z3 \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/opt-18 /usr/bin/opt && \
    ln -sf /usr/bin/llc-18 /usr/bin/llc && \
    ln -sf /usr/bin/lli-18 /usr/bin/lli && \
    ln -sf /usr/bin/llvm-as-18 /usr/bin/llvm-as && \
    ln -sf /usr/bin/llvm-dis-18 /usr/bin/llvm-dis

COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py

RUN mkdir -p /app

WORKDIR /app
