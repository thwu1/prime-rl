FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    g++ \
    clang \
    make \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/test_headers

COPY Makefile /app/Makefile
COPY vtable_engine.cpp /app/vtable_engine.cpp
COPY test_headers /app/test_headers

WORKDIR /app
