
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip xxd && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/ref

COPY FORMAT.md /app/FORMAT.md
COPY ref_frame.rs /app/ref/frame.rs
COPY ref_lib.rs /app/ref/lib.rs
COPY ref_parser.rs /app/ref/parser.rs

WORKDIR /app
