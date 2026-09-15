FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y gcc rustc cargo python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY c_src/ /app/c_src/
COPY rust_src/ /app/rust_src/
COPY data/ /app/data/

RUN gcc -O2 -o /app/c_src/record_processor /app/c_src/record_processor.c

RUN cd /app/rust_src && cargo build --release

WORKDIR /app
