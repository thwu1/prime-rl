
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
WORKDIR /app

COPY buggy_elliptic_core.c /app/elliptic_core.c
COPY buggy_elliptic.py /app/elliptic.py
RUN gcc -shared -fPIC -o /app/libelliptic.so /app/elliptic_core.c -lm
