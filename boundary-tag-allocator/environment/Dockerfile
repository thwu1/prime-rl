
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    binutils \
    file \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
WORKDIR /app

COPY myalloc_buggy.c /app/myalloc.c
RUN gcc -O2 -fPIC -shared -Wno-deprecated-declarations -o /app/libmyalloc.so /app/myalloc.c
