
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc make libgmp-dev && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/implementations

COPY implementations/main.c /app/implementations/main.c
COPY implementations/impl_alpha.c /app/implementations/impl_alpha.c
COPY implementations/impl_beta.c /app/implementations/impl_beta.c
COPY implementations/impl_gamma.c /app/implementations/impl_gamma.c
COPY implementations/Makefile /app/implementations/Makefile
COPY poly1305_ref.py /app/poly1305_ref.py
COPY test_vectors.json /app/test_vectors.json
COPY server_traffic.json /app/server_traffic.json
COPY target.json /app/target.json

WORKDIR /app
