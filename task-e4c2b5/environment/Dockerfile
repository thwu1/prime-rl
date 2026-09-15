FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        g++ \
        cmake \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/include

COPY spec.md /app/spec.md
COPY bipartite_buf_skeleton.hpp /app/include/bipartite_buf.hpp

WORKDIR /app
